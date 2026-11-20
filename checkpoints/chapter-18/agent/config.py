"""Settings, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import make_url

from agent.security import parse_clients

# Where conversations are stored when DATABASE_URL is not set: a file in the working folder.
DEFAULT_DATABASE_URL = "sqlite:///agent.db"

# Where the agent runs. The same image runs in all three; only the settings differ.
ENVIRONMENTS = ("local", "staging", "prod")

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
    # Settings built in code (as in the tests) get a database in memory, never a file.
    database_url: str = "sqlite://"
    app_env: str = "local"
    notes_url: str | None = None  # where the notes service is; None: no notes
    notes_api_key: str | None = None  # the key the notes service expects from us
    notes_timeout: float = 2.0  # seconds; a slow notes service must not hold the chat
    kafka_servers: str | None = None  # where Kafka is; None: no events are published
    # More clients, each with its own key: {sha256 of the key: client name} (AGENT_API_KEYS).
    api_clients: dict[str, str] = field(default_factory=dict)
    metrics_token: str | None = None  # what Prometheus sends to read /metrics; None: no /metrics
    rate_limit: int = 30  # /chat requests per client per minute
    max_steps: int = 5  # model calls in one agent run, at most (agent/loop.py)
    write_tools: bool = False  # may the model add and delete notes? (CHAT_WRITE_TOOLS=1)


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


def read_seconds(name: str, default: float) -> float:
    """Read a duration in seconds, more than 0, from an environment variable."""
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number of seconds, got {raw!r}.") from None
    if value <= 0:
        raise ConfigError(f"{name} must be more than 0, got {value}.")
    return value


def read_secret(name: str) -> str | None:
    """A secret from the file named in NAME_FILE (how secret stores hand them over), or NAME."""
    path = os.getenv(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError as error:
            raise ConfigError(f"{name}_FILE is {path!r}, which cannot be read.") from error
    return os.getenv(name) or None


def read_app_env() -> str:
    """APP_ENV: local (the default), staging or prod. Anything else is a typo, so stop."""
    app_env = os.getenv("APP_ENV", "local")
    if app_env not in ENVIRONMENTS:
        raise ConfigError(f"APP_ENV must be one of {', '.join(ENVIRONMENTS)}, got {app_env!r}.")
    return app_env


def database_url() -> str:
    """DATABASE_URL, with the password from DATABASE_PASSWORD(_FILE) when that is set.

    The URL says where the database is (configuration); the password is a secret.
    """
    url = os.getenv("DATABASE_URL")
    if url is None:
        if read_app_env() != "local":
            # A server must never fall back to a SQLite file inside its container.
            raise ConfigError("DATABASE_URL is not set. Outside local, it is required.")
        url = DEFAULT_DATABASE_URL
    password = read_secret("DATABASE_PASSWORD")
    if password:
        url = make_url(url).set(password=password).render_as_string(hide_password=False)
    return url


def read_clients() -> dict[str, str]:
    """AGENT_API_KEYS(_FILE): the hashed keys of the clients, as {hash: name}."""
    try:
        return parse_clients(read_secret("AGENT_API_KEYS") or "")
    except ValueError as error:
        raise ConfigError(f"AGENT_API_KEYS has a {error}.") from None


def load_settings() -> Settings:
    """Build the settings from environment variables, with defaults."""
    return Settings(
        model=os.getenv("CHAT_MODEL", "claude-opus-5-5"),
        mock=os.getenv("CHAT_MOCK", "0") == "1",
        agent_name=os.getenv("AGENT_NAME", "agent"),
        max_turns=read_positive_int("CHAT_MAX_TURNS", 10),
        api_key=read_secret("ANTHROPIC_API_KEY"),
        log_level=os.getenv("CHAT_LOG_LEVEL", "INFO").upper(),
        agent_api_key=read_secret("AGENT_API_KEY"),
        database_url=database_url(),
        app_env=read_app_env(),
        notes_url=os.getenv("NOTES_URL") or None,
        notes_api_key=read_secret("NOTES_API_KEY"),
        notes_timeout=read_seconds("NOTES_TIMEOUT", 2.0),
        kafka_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS") or None,
        api_clients=read_clients(),
        metrics_token=read_secret("METRICS_TOKEN"),
        rate_limit=read_positive_int("CHAT_RATE_LIMIT", 30),
        max_steps=read_positive_int("CHAT_MAX_STEPS", 5),
        write_tools=os.getenv("CHAT_WRITE_TOOLS", "0") == "1",
    )
