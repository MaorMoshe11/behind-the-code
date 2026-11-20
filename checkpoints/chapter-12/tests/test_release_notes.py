"""The release check: run the script as the release workflow does."""

import subprocess
import sys
from pathlib import Path

from agent import project_version

ROOT = Path(__file__).resolve().parent.parent


def release_notes(tag):
    return subprocess.run(
        [sys.executable, "scripts/release_notes.py", tag],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_the_current_version_has_release_notes():
    # Fails as soon as pyproject.toml gets a new version without a CHANGELOG.md section.
    result = release_notes(f"v{project_version()}")
    assert result.returncode == 0, result.stderr
    assert "### " in result.stdout


def test_a_wrong_tag_stops_the_release():
    result = release_notes("v0.0.1")
    assert result.returncode == 1
    assert "does not match" in result.stderr
