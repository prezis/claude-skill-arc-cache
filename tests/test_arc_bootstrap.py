"""Smoke tests for arc-bootstrap.sh — proves the loader produces valid output."""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "hooks" / "scripts" / "arc-bootstrap.sh"


def test_arc_bootstrap_loads_simple_cluster(tmp_arcs_dir, tmp_path):
    """Two small files in a config produce a valid dump."""
    file_a = tmp_path / "a.md"
    file_a.write_text("# Document A\nFirst file in the arc.\n")
    file_b = tmp_path / "b.md"
    file_b.write_text("# Document B\nSecond file.\n")

    conf = tmp_arcs_dir / "test.conf"
    conf.write_text(f"{file_a}\n{file_b}\n")

    result = subprocess.run(
        ["bash", str(SCRIPT), "test"],
        capture_output=True, text=True,
        env={"HOME": str(tmp_arcs_dir.parents[2])},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "## arc-bootstrap: a.md" in result.stdout
    assert "## arc-bootstrap: b.md" in result.stdout
    assert "## arc-bootstrap summary" in result.stdout
    assert "Files loaded: 2" in result.stdout


def test_arc_bootstrap_missing_config_exits_2(tmp_arcs_dir):
    """Missing config → exit code 2 + helpful error on stderr."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "nonexistent"],
        capture_output=True, text=True,
        env={"HOME": str(tmp_arcs_dir.parents[2])},
    )
    assert result.returncode == 2
    assert "arc config not found" in result.stderr


def test_arc_bootstrap_skips_binary_files(tmp_arcs_dir, tmp_path):
    """Binary files in cluster get skipped with [BINARY-SKIPPED] marker."""
    bin_file = tmp_path / "fake.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03" * 100)

    conf = tmp_arcs_dir / "binsmoke.conf"
    conf.write_text(f"{bin_file}\n")

    result = subprocess.run(
        ["bash", str(SCRIPT), "binsmoke"],
        capture_output=True, text=True,
        env={"HOME": str(tmp_arcs_dir.parents[2])},
    )
    assert result.returncode == 0
    assert "[BINARY-SKIPPED]" in result.stdout


def test_arc_bootstrap_handles_missing_file_in_config(tmp_arcs_dir):
    """A non-existent path in config is reported, not fatal."""
    conf = tmp_arcs_dir / "miss.conf"
    conf.write_text("/this/path/does/not/exist.md\n")

    result = subprocess.run(
        ["bash", str(SCRIPT), "miss"],
        capture_output=True, text=True,
        env={"HOME": str(tmp_arcs_dir.parents[2])},
    )
    assert result.returncode == 0
    assert "[MISSING]" in result.stdout
