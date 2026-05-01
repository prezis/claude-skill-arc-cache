#!/usr/bin/env python3
"""
Stop hook: extract Anthropic prompt-cache telemetry from a session JSONL transcript.

Appends ONE rolled-up JSONL line per Stop event to ~/.claude/state/cache-stats.jsonl.

Design (s23, 2026-05-01):
- Hook contract: pure side-effect logger. Reads {session_id, transcript_path} from
  stdin (Stop hook protocol), writes nothing to stdout, never blocks stop. Always
  returns 0 even on internal failure (errors logged to cache-stats-errors.jsonl).
- Idempotent: progress sidecar tracks last_offset per session_id; re-runs process
  only the new tail.
- Stream + flock: O(1) memory, atomic appends, RMW-safe progress updates.

Verified field shape across 6 transcripts / 2447 records (step 1a):
- type==assistant records carry message.usage with:
    input_tokens, cache_read_input_tokens, cache_creation_input_tokens,
    output_tokens, service_tier (sometimes null),
    cache_creation: {ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}

Pricing source: docs.anthropic.com/.../prompt-caching (fetched 2026-05-01).
Hardcoded for Opus 4.5; TODO model-aware pricing once we have multi-model sessions.

Bugs fixed in v1 (per local_code_review):
- f.readline() replaces `for line in f` + f.tell() (TextIOWrapper buffer bug)
- file-size guard resets offset on rotation/truncation
- LOCK_EX on load_progress to prevent RMW race between concurrent Stops
- warning lines emit full zero-shape so downstream rollup never KeyErrors
- skipped_lines counter surfaces silent JSON corruption (e.g. partial last line)

CLI fallback:
    cat <stop-event-payload.json> | cache-stats-extractor.py --replay
    (resets last_offset for the session_id in payload, reprocesses from 0)
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Pricing (Opus 4.5, $/token).
# Source: docs.anthropic.com/en/docs/build-with-claude/prompt-caching, 2026-05-01.
# 5m write = 1.25x base, 1h write = 2x base, cache read = 0.1x base.
# TODO(model-aware): when transcript carries model_id consistently, switch to a
# {model: rates} map and pick per-record. Until then we treat all sessions as
# Opus 4.5 - fine for the Anthropic-Max plan + arc workflows.
# ---------------------------------------------------------------------------
OPUS_4_5_BASE_INPUT = 5.00 / 1_000_000
OPUS_4_5_CACHE_READ = 0.50 / 1_000_000
OPUS_4_5_CACHE_WRITE_5M = 6.25 / 1_000_000
OPUS_4_5_CACHE_WRITE_1H = 10.00 / 1_000_000
OPUS_4_5_OUTPUT = 25.00 / 1_000_000

STATE_DIR = Path.home() / ".claude" / "state"
OUTPUT_FILE = STATE_DIR / "cache-stats.jsonl"
PROGRESS_FILE = STATE_DIR / "cache-stats-progress.json"
PROGRESS_LOCK = STATE_DIR / "cache-stats-progress.lock"
ERROR_FILE = STATE_DIR / "cache-stats-errors.jsonl"

ZERO_TOKENS: Dict[str, int] = {
    "uncached_input": 0,
    "cache_read": 0,
    "cache_write_5m": 0,
    "cache_write_1h": 0,
    "output": 0,
}
ZERO_COST: Dict[str, float] = {
    "actual": 0.0,
    "uncached_baseline": 0.0,
    "saved": 0.0,
    "saved_pct": 0.0,
}
ZERO_BREAKDOWN: Dict[str, float] = {"1h_share_pct": 0.0, "cache_hit_pct": 0.0}


def log_error(msg: str) -> None:
    """Best-effort error logging. Never raises."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(ERROR_FILE, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps({"ts": time.time(), "error": msg}) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def load_progress() -> Dict[str, Dict[str, Any]]:
    """Read progress sidecar. Caller must wrap with progress_locked() for
    EXCLUSIVE coordination across the load+modify+save cycle."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not PROGRESS_FILE.exists():
            return {}
        with open(PROGRESS_FILE, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        return {}


def save_progress(progress: Dict[str, Dict[str, Any]]) -> None:
    """Atomically replace progress sidecar. Caller must hold progress_locked()."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = PROGRESS_FILE.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(progress, f)
        os.replace(tmp_file, PROGRESS_FILE)
    except Exception as e:
        log_error(f"save_progress failed: {e}")


class progress_locked:
    """Context manager: holds exclusive lock on PROGRESS_LOCK across the
    load -> modify -> save cycle. Prevents the RMW race flagged by review."""

    def __enter__(self) -> "progress_locked":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock_fp = open(PROGRESS_LOCK, "a+")
        fcntl.flock(self._lock_fp.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            fcntl.flock(self._lock_fp.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_fp.close()


def process_transcript(
    transcript_path: str,
    start_offset: int,
) -> Optional[Dict[str, Any]]:
    """Stream transcript from start_offset, aggregate per-turn usage.

    Uses readline() in a while-loop because `for line in f` + f.tell() is
    broken on TextIOWrapper (buffered reads return wrong offsets).

    Handles file rotation: if file size < start_offset, transcript was
    truncated/replaced; reset to 0 and log a warning.
    """
    try:
        try:
            file_size = os.path.getsize(transcript_path)
        except OSError as e:
            log_error(f"stat failed: {transcript_path}: {e}")
            return None
        if file_size < start_offset:
            log_error(
                f"file shrunk (size={file_size} < offset={start_offset}); "
                f"resetting offset to 0 for {transcript_path}"
            )
            start_offset = 0

        stats: Dict[str, Any] = {
            "assistant_turns": 0,
            "skipped_lines": 0,
            "tokens": dict(ZERO_TOKENS),
            "service_tiers": set(),
        }

        with open(transcript_path, "r") as f:
            f.seek(start_offset)
            current_offset = start_offset
            while True:
                line = f.readline()
                if not line:
                    break
                current_offset = f.tell()
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    stats["skipped_lines"] += 1
                    continue
                if record.get("type") != "assistant":
                    continue
                usage = (record.get("message") or {}).get("usage")
                if not usage:
                    continue
                stats["assistant_turns"] += 1
                t = stats["tokens"]
                t["uncached_input"] += int(usage.get("input_tokens") or 0)
                t["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
                t["output"] += int(usage.get("output_tokens") or 0)
                cc = usage.get("cache_creation") or {}
                t["cache_write_5m"] += int(cc.get("ephemeral_5m_input_tokens") or 0)
                t["cache_write_1h"] += int(cc.get("ephemeral_1h_input_tokens") or 0)
                tier = usage.get("service_tier")
                stats["service_tiers"].add(tier if tier is not None else "null")

            return {"stats": stats, "end_offset": current_offset}
    except Exception as e:
        log_error(f"process_transcript failed: {e}")
        return None


def compute_costs(tokens: Dict[str, int]) -> Dict[str, float]:
    """Cost & savings math.

    Semantic note: `saved` is `uncached_baseline - actual`. Baseline assumes
    EVERY input token billed at base price (no caching). Since cache reads
    cost 10% of base and writes cost 125%/200%, savings is positive when
    reads dominate writes (steady state). For one-shot sessions with no
    reuse, savings can be slightly negative (write surcharge alone). Correct
    counterfactual for "is caching helping me?"
    """
    actual = (
        tokens["uncached_input"] * OPUS_4_5_BASE_INPUT
        + tokens["cache_read"] * OPUS_4_5_CACHE_READ
        + tokens["cache_write_5m"] * OPUS_4_5_CACHE_WRITE_5M
        + tokens["cache_write_1h"] * OPUS_4_5_CACHE_WRITE_1H
        + tokens["output"] * OPUS_4_5_OUTPUT
    )
    total_input = (
        tokens["uncached_input"]
        + tokens["cache_read"]
        + tokens["cache_write_5m"]
        + tokens["cache_write_1h"]
    )
    baseline = total_input * OPUS_4_5_BASE_INPUT + tokens["output"] * OPUS_4_5_OUTPUT
    saved = baseline - actual
    saved_pct = round((saved / baseline) * 100, 1) if baseline > 0 else 0.0
    return {
        "actual": round(actual, 6),
        "uncached_baseline": round(baseline, 6),
        "saved": round(saved, 6),
        "saved_pct": saved_pct,
    }


def compute_breakdown(tokens: Dict[str, int]) -> Dict[str, float]:
    cache_write_total = tokens["cache_write_1h"] + tokens["cache_write_5m"]
    total_input_for_hit = tokens["uncached_input"] + tokens["cache_read"]
    return {
        "1h_share_pct": (
            round(tokens["cache_write_1h"] / cache_write_total * 100, 1)
            if cache_write_total > 0 else 0.0
        ),
        "cache_hit_pct": (
            round(tokens["cache_read"] / total_input_for_hit * 100, 1)
            if total_input_for_hit > 0 else 0.0
        ),
    }


def write_output_line(data: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(data) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        log_error(f"write_output_line failed: {e}")


def emit_warning(session_id: str, transcript_path: str, reason: str) -> None:
    """Emit a warning line preserving full output schema with zero metrics."""
    write_output_line({
        "ts": time.time(),
        "session_id": session_id,
        "transcript_path": transcript_path,
        "warning": reason,
        "assistant_turns": 0,
        "skipped_lines": 0,
        "tokens": dict(ZERO_TOKENS),
        "cost_usd": dict(ZERO_COST),
        "service_tier_seen": [],
        "tier_breakdown": dict(ZERO_BREAKDOWN),
    })


def main() -> int:
    try:
        replay = len(sys.argv) > 1 and sys.argv[1] == "--replay"
        try:
            input_data = json.load(sys.stdin)
        except Exception:
            return 0

        session_id = input_data.get("session_id", "unknown")
        transcript_path = input_data.get("transcript_path", "")

        if not transcript_path:
            emit_warning(session_id, "", "transcript_path missing")
            return 0
        if not os.path.isfile(transcript_path):
            emit_warning(session_id, transcript_path, "transcript file not found")
            return 0

        with progress_locked():
            progress = load_progress()
            session_progress = progress.get(session_id, {})
            start_offset = 0 if replay else int(session_progress.get("last_offset", 0))

            result = process_transcript(transcript_path, start_offset)
            if not result:
                emit_warning(session_id, transcript_path, "processing failed")
                return 0

            stats = result["stats"]
            end_offset = result["end_offset"]

            t = stats["tokens"]
            output_line = {
                "ts": time.time(),
                "session_id": session_id,
                "transcript_path": transcript_path,
                "assistant_turns": stats["assistant_turns"],
                "skipped_lines": stats["skipped_lines"],
                "tokens": t,
                "cost_usd": compute_costs(t),
                "service_tier_seen": sorted(stats["service_tiers"]),
                "tier_breakdown": compute_breakdown(t),
                "replay": replay,
            }
            write_output_line(output_line)

            progress[session_id] = {
                "last_offset": end_offset,
                "last_run_ts": time.time(),
            }
            save_progress(progress)

    except Exception as e:
        log_error(f"main: unhandled: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
