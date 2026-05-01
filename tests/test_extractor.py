"""Smoke test for cache-stats-extractor.py — verifies it parses a synthetic
transcript and writes a valid JSONL line with the expected schema."""
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "hooks" / "scripts" / "cache-stats-extractor.py"


def make_transcript(path, n_assistant_turns=3):
    """Write a fake transcript JSONL with N assistant records."""
    with open(path, "w") as f:
        for i in range(n_assistant_turns):
            rec = {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 5000 + i * 100,
                        "cache_creation_input_tokens": 1000 if i == 0 else 0,
                        "output_tokens": 200,
                        "service_tier": "standard",
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 1000 if i == 0 else 0,
                        },
                    }
                },
            }
            f.write(json.dumps(rec) + "\n")


def test_extractor_writes_valid_jsonl(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    state = fake_home / ".claude" / "state"
    state.mkdir(parents=True)

    transcript = tmp_path / "transcript.jsonl"
    make_transcript(transcript)

    payload = json.dumps({
        "session_id": "test-session-abc",
        "transcript_path": str(transcript),
    })

    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=payload, capture_output=True, text=True,
        env={"HOME": str(fake_home)},
    )
    assert result.returncode == 0
    out_file = state / "cache-stats.jsonl"
    assert out_file.exists()
    line = out_file.read_text().strip()
    obj = json.loads(line)
    assert obj["session_id"] == "test-session-abc"
    assert obj["assistant_turns"] == 3
    assert obj["tokens"]["cache_read"] > 0
    assert obj["cost_usd"]["actual"] > 0
    assert obj["cost_usd"]["saved"] > 0
    assert obj["tier_breakdown"]["1h_share_pct"] == 100.0
