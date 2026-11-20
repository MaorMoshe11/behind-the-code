"""The database: two tables, and the engine that connects to them.

DATABASE_URL says which database. The default is a SQLite file, agent.db.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, ForeignKey, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Every table class inherits from this, so SQLAlchemy knows about all of them."""


class ConversationRow(Base):
    """One row of the conversations table."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class MessageRow(Base):
    """One row of the messages table: one message, in one conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)


def turn_on_foreign_keys(connection: Any, record: Any) -> None:
    """SQLite ignores foreign keys unless every new connection asks for them."""
    connection.execute("PRAGMA foreign_keys = ON")


def make_engine(url: str) -> Engine:
    """Connect to the database at `url`, and create the tables that do not exist yet."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        # An in-memory database lives inside one connection, so everyone shares that one.
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", turn_on_foreign_keys)
    # create_all adds missing tables. It never changes a table that already exists.
    Base.metadata.create_all(engine)
    return engine
