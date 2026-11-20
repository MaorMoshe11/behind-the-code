"""The notes service's settings, read from environment variables.

The helpers are copied from the chat service on purpose: two services share a contract
(the HTTP API), not code. Ten copied lines are cheaper than a library both must update.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

ENVIRONMENTS = ("local", "staging", "prod")


class ConfigError(Exception):
    """A setting has a value the service cannot use."""


@dataclass(frozen=True)
class Settings:
    api_key: str  # the key the chat service sends in X-API-Key
    database_url: str = "sqlite://"  # settings built in code (the tests): in memory
    app_env: str = "local"
    # Fault injection, for learning what a network call can do. Never on in prod.
    delay_seconds: float = 0.0  # wait this long before every answer: a slow service
    fail_after_save: bool = False  # save the note, then answer 500: the answer is "lost"


def read_secret(name: str) -> str | None:
    """A secret from the file named in NAME_FILE, or from NAME."""
    path = os.getenv(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError as error:
            raise ConfigError(f"{name}_FILE is {path!r}, which cannot be read.") from error
    return os.getenv(name) or None


def load_settings() -> Settings:
    """Build the settings from environment variables, with defaults."""
    app_env = os.getenv("APP_ENV", "local")
    if app_env not in ENVIRONMENTS:
        raise ConfigError(f"APP_ENV must be one of {', '.join(ENVIRONMENTS)}, got {app_env!r}.")
    api_key = read_secret("NOTES_API_KEY")
    if not api_key:
        raise ConfigError("NOTES_API_KEY is not set.")
    url = os.getenv("DATABASE_URL", "sqlite:///notes.db")
    password = read_secret("DATABASE_PASSWORD")
    if password:
        url = make_url(url).set(password=password).render_as_string(hide_password=False)
    delay = float(os.getenv("NOTES_DELAY_SECONDS", "0"))
    fail_after_save = os.getenv("NOTES_FAIL_AFTER_SAVE", "0") == "1"
    if app_env == "prod" and (delay or fail_after_save):
        raise ConfigError("Fault injection is for learning: it is refused in prod.")
    return Settings(api_key, url, app_env, delay, fail_after_save)
