"""Settings, read from environment variables."""

import os
from dataclasses import dataclass

SYSTEM_PROMPT = (
    "You are a friendly assistant. Keep your answers short and clear. "
    "Answer in the language the user writes in."
)


class ConfigError(Exception):
    """A setting has a value the program cannot use."""


@dataclass(frozen=True)
class Settings:
    model: str
    mock: bool
    agent_name: str
    max_turns: int
    api_key: str | None
    log_level: str = "INFO"
    agent_api_key: str | None = None  # the key clients must send to our own API


def read_positive_int(name: str, default: int) -> int:
    """Read a whole number of 1 or more from an environment variable."""
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value < 1:
        raise ConfigError(f"{name} must be 1 or more, got {value}.")
    return value


def load_settings() -> Settings:
    """Build the settings from environment variables, with defaults."""
    return Settings(
        model=os.getenv("CHAT_MODEL", "claude-opus-5-5"),
        mock=os.getenv("CHAT_MOCK", "0") == "1",
        agent_name=os.getenv("AGENT_NAME", "agent"),
        max_turns=read_positive_int("CHAT_MAX_TURNS", 10),
        api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        log_level=os.getenv("CHAT_LOG_LEVEL", "INFO").upper(),
        agent_api_key=os.getenv("AGENT_API_KEY") or None,
    )
