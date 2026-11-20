"""The notes service's own database: one table. No other service reads or writes it."""

from datetime import UTC, datetime

from sqlalchemy import Engine, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


def now() -> datetime:
    """UTC, stored without a time zone (the same on SQLite and Postgres)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Every table class inherits from this."""


class NoteRow(Base):
    """One note, attached to one conversation of the chat service."""

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # The chat service's id, kept as plain text: there is no foreign key to another
    # service's database. This service cannot check that the conversation exists.
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)
    # The client's Idempotency-Key. unique: the database itself refuses a second note
    # with the same key, even when two requests arrive at the same moment.
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)


def make_engine(url: str) -> Engine:
    """Connect, and create the table if it is missing.

    One table and no data to keep yet, so create_all is enough. The first change to the
    table brings Alembic, exactly as in the chat service (chapter 7).
    """
    if url in ("sqlite://", "sqlite:///:memory:"):
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    elif url.startswith("postgresql"):
        engine = create_engine(url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
    else:
        engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine
