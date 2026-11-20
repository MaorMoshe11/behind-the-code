"""my-agent: a small chat agent on the Claude API."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def project_version() -> str:
    """The version of the project: written once, in pyproject.toml, and read from there."""
    with PYPROJECT.open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])
