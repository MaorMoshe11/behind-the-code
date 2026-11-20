"""Print the notes of one release from CHANGELOG.md, after checking that the tag is right.

    uv run python scripts/release_notes.py v0.9.0

Exits with an error when the tag does not match the version in pyproject.toml, or when
CHANGELOG.md has no section for it: then the release workflow stops before it builds.
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])


def notes(version: str, changelog: str) -> str | None:
    """The text under '## [version]', up to the next '## ' heading."""
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)"
    found = re.search(pattern, changelog, re.MULTILINE | re.DOTALL)
    return found.group(1).strip() if found else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a release tag and print its notes.")
    parser.add_argument("tag", help="the git tag, for example v0.9.0")
    tag = parser.parse_args().tag
    version = project_version()
    if tag != f"v{version}":
        sys.exit(f"The tag {tag} does not match the version in pyproject.toml ({version}).")
    text = notes(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    if not text:
        sys.exit(f"CHANGELOG.md has no notes for {version}.")
    print(text)


if __name__ == "__main__":
    main()
