"""The notes service: short notes attached to the chat service's conversations."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def project_version() -> str:
    """This service's own version, from its own pyproject.toml."""
    with PYPROJECT.open("rb") as file:
        return str(tomllib.load(file)["project"]["version"])
