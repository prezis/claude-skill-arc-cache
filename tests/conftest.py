import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPTS = REPO_ROOT / "hooks" / "scripts"
sys.path.insert(0, str(HOOK_SCRIPTS))


@pytest.fixture
def tmp_arcs_dir(tmp_path, monkeypatch):
    """Isolated ARCS_DIR + STATE_DIR for tests, no pollution of real ~/.claude."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # arc-bootstrap reads $HOME/.claude/state/arcs/<slug>.conf
    arcs = fake_home / ".claude" / "state" / "arcs"
    arcs.mkdir(parents=True)
    yield arcs
