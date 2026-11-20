"""One Python version for everything: written once, in .python-version.

uv reads that file on your computer and in CI. The Dockerfile cannot read it, so this
test makes sure the image starts FROM the same version, and that the tests run on it.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pinned_version():
    return (ROOT / ".python-version").read_text(encoding="utf-8").strip()


def test_the_image_uses_the_pinned_python():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM python:(\S+)-slim", dockerfile, re.MULTILINE)
    assert base is not None, "the Dockerfile does not start FROM python:<version>-slim"
    assert base.group(1) == pinned_version()


def test_the_tests_run_on_the_pinned_python():
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert running == pinned_version()
