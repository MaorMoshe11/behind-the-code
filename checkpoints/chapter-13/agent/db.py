"""The database: two tables, and the engine that connects to them.

DATABASE_URL says which database. The default is a SQLite file, agent.db.
The tables of a real database are created and changed only by migrations (migrations/).
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, ForeignKey, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).parent.parent / "migrations"


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Every table class inherits from this, so SQLAlchemy knows about all of them."""


class ConversationRow(Base):
    """One row of the conversations table."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Who the conversation belongs to. Empty for now: the "expand" step (chapter 7).
    user_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
    # Set while the conversation is being deleted (the first step of the saga): hidden.
    archived_at: Mapped[datetime | None]


class MessageRow(Base):
    """One row of the messages table: one message, in one conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)


class DatabaseNotReady(Exception):
    """The database is missing migrations that this code needs."""


def turn_on_foreign_keys(connection: Any, record: Any) -> None:
    """SQLite ignores foreign keys unless every new connection asks for them."""
    connection.execute("PRAGMA foreign_keys = ON")


def alembic_config(url: str) -> Config:
    """What the alembic command reads from alembic.ini, for the database at `url`."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["url"] = url  # migrations/env.py reads it from here
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Run the migrations on the database at `url`, like `alembic upgrade head`."""
    command.upgrade(alembic_config(url), revision)


def check_schema(engine: Engine) -> None:
    """Refuse to work with a database that is behind the code."""
    scripts = ScriptDirectory(str(MIGRATIONS))
    head = scripts.get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current == head:
        return
    if current is None:
        raise DatabaseNotReady(
            "The database has no migration history. A new database: run "
            "`uv run alembic upgrade head`. One from before migrations: see `alembic stamp`."
        )
    try:
        scripts.get_revision(current)
    except CommandError:
        # A revision we do not know: newer code has already migrated this database.
        # That is fine (the old code must keep working during a deploy), but say so.
        log.warning("database is at %s, newer than this code (%s)", current, head)
        return
    raise DatabaseNotReady(
        f"The database is at revision {current}, the code needs {head}. "
        "Run `uv run alembic upgrade head`."
    )


def make_engine(url: str) -> Engine:
    """Connect to the database at `url`, and make sure its tables match the code."""
    in_memory = url in ("sqlite://", "sqlite:///:memory:")
    if in_memory:
        # An in-memory database lives inside one connection, so everyone shares that one.
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    elif url.startswith("postgresql"):
        # A server that is down must fail fast (connect_timeout, in seconds), and a connection
        # left over from before a database restart is tested before use (pool_pre_ping).
        engine = create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
    else:
        engine = create_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", turn_on_foreign_keys)
    if in_memory:
        # A new, empty database that disappears with the process (the tests): nothing to
        # migrate, so the tables come straight from the classes above.
        Base.metadata.create_all(engine)
    else:
        check_schema(engine)
    return engine
