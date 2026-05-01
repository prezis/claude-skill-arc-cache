#!/usr/bin/env python3
"""
UserPromptSubmit hook — auto-fire arc-bootstrap on natural-language recall intent.

Triggers when BOTH conditions hold in the user prompt:
  (a) a recall/intent verb in PL or EN ("wracamy do", "przypomnij", "remind me",
      "what's the goal", "where did we leave off", etc.)
  (b) a project keyword that matches an arc with a config in ~/.claude/state/arcs/

When both fire, runs ~/.claude/state/scripts/arc-bootstrap.sh <slug> and injects
the output as additionalContext in the user's turn — so the cluster lands as
one user message and becomes the cache prefix.

Session dedup: once injected for (session_id, slug), skipped on subsequent
matching prompts in the same session (small breadcrumb is emitted instead).

Bypass: CLAUDE_FORCE_NO_ARC=1 → no-op, audit-logged.

Designed s23 / 2026-05-01 to close the "user has to remember /arc-<slug>" gap.
Sibling of recall-graph-rag.py — that one fires on broader recall + injects
truncated excerpts; this one fires on tighter intent + injects full cluster.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HOME = Path.home()
STATE_DIR = HOME / ".claude" / "state"
ARCS_DIR = STATE_DIR / "arcs"
BOOTSTRAP = STATE_DIR / "scripts" / "arc-bootstrap.sh"
INJECTED_STATE = STATE_DIR / "arc-auto-trigger-injected.json"
INJECTED_LOCK = STATE_DIR / "arc-auto-trigger-injected.lock"
LOG_FILE = STATE_DIR / "arc-auto-trigger-log.jsonl"
ERROR_FILE = STATE_DIR / "arc-auto-trigger-errors.jsonl"
BYPASS_LOG = STATE_DIR / "bypass-log.jsonl"

# Bilingual / synonym aliases for projects whose memory-file slug differs
# from the natural way humans refer to them. Keys = arc slugs (basename of
# .conf in ARCS_DIR). Values = phrases that should map to that slug.
#
# Default ships EMPTY. Power users add aliases per their projects via:
#     ~/.claude/state/arcs/aliases.json
# Format: {"<slug>": ["alias1", "alias2", ...], ...}
# See examples/aliases.json.example in the repo for a sample.
#
# Tip: keep aliases at least 2 words long for project keywords that have
# generic English meanings (e.g. "lora" alone is too broad — use "lora training").
HARD_ALIASES: Dict[str, List[str]] = {}

ALIASES_FILE = Path.home() / ".claude" / "state" / "arcs" / "aliases.json"
if ALIASES_FILE.exists():
    try:
        loaded = json.loads(ALIASES_FILE.read_text())
        if isinstance(loaded, dict):
            HARD_ALIASES = {
                str(k): [str(v) for v in vs]
                for k, vs in loaded.items()
                if isinstance(vs, list)
            }
    except Exception:
        # Bad JSON in aliases.json shouldn't break the hook
        pass

# Recall verbs (regex; assembled into one alternation pattern at module load).
RECALL_PATTERNS = [
    # Polish
    r"wracamy(?:\s+do)?",
    r"wracaj[aą]c(?:\s+do)?",
    r"kontynuujmy?",
    r"kontynuuj",
    r"przypomnij(?:\s+(?:sobie|mi))?",
    r"powr[oó]t",
    r"gdzie\s+sko[nń]czyli[sś]my",
    r"co\s+robimy(?:\s+z)?",
    r"co\s+(?:dalej|z)\s+",
    r"jaki\s+(?:jest\s+)?(?:nasz\s+)?(?:cel|gol|plan|target)",
    r"co\s+to\s+za\s+projekt",
    r"o\s+czym\s+(?:jest|byl|by[lł]o)",
    # English
    r"remind\s+me",
    r"what(?:'s|\s+is)\s+(?:this|that)\s+project",
    r"where\s+(?:did\s+we\s+leave|are\s+we)",
    r"pick\s+up\s+where",
    r"what(?:'s|\s+is)\s+(?:the|our)\s+(?:goal|target|plan)",
    r"resume\s+(?:the|this|our)",
]
RECALL_RE = re.compile(r"\b(?:" + "|".join(RECALL_PATTERNS) + r")\b", re.IGNORECASE)


def _log(path: Path, entry: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def discover_arc_keywords() -> Dict[str, List[str]]:
    """Build {slug: [keywords...]} from ARCS_DIR plus HARD_ALIASES."""
    out: Dict[str, List[str]] = {}
    if not ARCS_DIR.exists():
        return out
    for conf in ARCS_DIR.glob("*.conf"):
        slug = conf.stem
        kws = [slug]
        if "_" in slug:
            kws.append(slug.replace("_", " "))
            kws.append(slug.replace("_", "-"))
        kws.extend(HARD_ALIASES.get(slug, []))
        # Dedup, keep order, lowercase for matching later
        seen = set()
        out[slug] = [k for k in kws if not (k.lower() in seen or seen.add(k.lower()))]
    return out


def detect(prompt: str, arc_kws: Dict[str, List[str]]) -> Optional[Tuple[str, str, str]]:
    """Return (slug, matched_verb, matched_keyword) or None."""
    if not prompt or not arc_kws:
        return None
    prompt_lower = prompt.lower()
    verb_match = RECALL_RE.search(prompt_lower)
    if not verb_match:
        return None
    matched_verb = verb_match.group(0)

    best: Optional[Tuple[str, str, int]] = None
    for slug, kws in arc_kws.items():
        for kw in kws:
            kw_low = kw.lower()
            # short keywords get word-boundary anchoring to avoid false matches
            if len(kw_low) <= 4:
                if not re.search(r"\b" + re.escape(kw_low) + r"\b", prompt_lower):
                    continue
            else:
                if kw_low not in prompt_lower:
                    continue
            score = len(kw_low)
            if best is None or score > best[2]:
                best = (slug, kw, score)
    if not best:
        return None
    return (best[0], matched_verb, best[1])


def load_injected() -> Dict[str, List[str]]:
    if not INJECTED_STATE.exists():
        return {}
    try:
        with open(INJECTED_STATE, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        return {}


def save_injected(state: Dict[str, List[str]]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(INJECTED_LOCK, "a+") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                tmp = INJECTED_STATE.with_suffix(".tmp")
                tmp.write_text(json.dumps(state))
                os.replace(tmp, INJECTED_STATE)
            finally:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        _log(ERROR_FILE, {"ts": time.time(), "save_injected_failed": str(e)})


def run_bootstrap(slug: str) -> Optional[str]:
    if not BOOTSTRAP.exists():
        _log(ERROR_FILE, {"ts": time.time(), "missing_bootstrap": str(BOOTSTRAP)})
        return None
    try:
        r = subprocess.run(
            ["bash", str(BOOTSTRAP), slug],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0 or len(r.stdout) < 1000 or r.stdout.startswith("ERROR"):
            _log(ERROR_FILE, {
                "ts": time.time(), "slug": slug,
                "rc": r.returncode, "stdout_len": len(r.stdout),
                "stderr_head": r.stderr[:300],
            })
            return None
        return r.stdout
    except subprocess.TimeoutExpired:
        _log(ERROR_FILE, {"ts": time.time(), "slug": slug, "error": "timeout"})
        return None
    except Exception as e:
        _log(ERROR_FILE, {"ts": time.time(), "slug": slug, "error": repr(e)[:200]})
        return None


def main() -> int:
    try:
        # Bypass
        if os.environ.get("CLAUDE_FORCE_NO_ARC") == "1":
            _log(BYPASS_LOG, {
                "ts": time.time(),
                "hook": "arc-auto-trigger",
                "reason": "CLAUDE_FORCE_NO_ARC=1",
            })
            return 0

        try:
            payload = json.load(sys.stdin)
        except Exception:
            return 0

        prompt = payload.get("prompt", "") or ""
        session_id = payload.get("session_id", "unknown")
        if not prompt:
            return 0

        arc_kws = discover_arc_keywords()
        det = detect(prompt, arc_kws)
        if not det:
            return 0
        slug, verb, keyword = det

        state = load_injected()
        if session_id in state and slug in state[session_id]:
            ctx = f"[arc-{slug} already injected earlier this session — skipping re-injection. " \
                  f"Manual re-load: /arc-{slug}]"
            _log(LOG_FILE, {
                "ts": time.time(), "type": "skip_dedup",
                "session_id": session_id, "slug": slug,
                "verb": verb, "keyword": keyword,
            })
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": ctx,
                }
            }), flush=True)
            return 0

        out = run_bootstrap(slug)
        if not out:
            _log(LOG_FILE, {
                "ts": time.time(), "type": "skip_bootstrap_failed",
                "session_id": session_id, "slug": slug,
            })
            return 0

        envelope = (
            f'<arc-auto-trigger source="arc-auto-trigger.py" slug="{slug}" '
            f'reason="verb={verb!r}+kw={keyword!r}">\n'
            + out +
            "\n</arc-auto-trigger>"
        )
        # Update dedup state
        state.setdefault(session_id, []).append(slug)
        # Cap state file at last 50 sessions to bound size
        if len(state) > 50:
            keep = list(state.keys())[-50:]
            state = {k: state[k] for k in keep}
        save_injected(state)

        _log(LOG_FILE, {
            "ts": time.time(), "type": "fire",
            "session_id": session_id, "slug": slug,
            "verb": verb, "keyword": keyword,
            "output_bytes": len(out),
        })
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": envelope,
            }
        }), flush=True)
        return 0
    except Exception as e:
        _log(ERROR_FILE, {"ts": time.time(), "main_unhandled": repr(e)[:200]})
        return 0


if __name__ == "__main__":
    sys.exit(main())
