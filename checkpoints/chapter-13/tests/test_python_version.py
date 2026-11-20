"""One Python version for everything: written once, in .python-version.

uv reads that file on your computer and in CI. The Dockerfile cannot read it, so this
test makes sure both images start FROM the same version, and that the tests run on it.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def pinned_version():
    return (ROOT / ".python-version").read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "notes-service/Dockerfile"])
def test_the_images_use_the_pinned_python(dockerfile):
    dockerfile = (ROOT / dockerfile).read_text(encoding="utf-8")
    base = re.search(r"^FROM python:(\S+)-slim", dockerfile, re.MULTILINE)
    assert base is not None, "the Dockerfile does not start FROM python:<version>-slim"
    assert base.group(1) == pinned_version()


def test_the_tests_run_on_the_pinned_python():
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert running == pinned_version()


def test_the_notes_service_pins_the_same_python():
    notes_pin = (ROOT / "notes-service" / ".python-version").read_text(encoding="utf-8").strip()
    assert notes_pin == pinned_version()
