"""Usage statistics, built from the chat's events. No Kafka here: this part is plain Python.

The statistics are derived data. They live in the worker's own small database, and they
can always be rebuilt by reading the events again from the beginning.
"""

import json
from typing import Any

from sqlalchemy import Engine, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """The worker's tables. They are not in the chat's database."""


class UsageRow(Base):
    """How much one conversation has been used."""

    __tablename__ = "usage"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)


class ProcessedEvent(Base):
    """Every event this worker has already applied: the memory of an idempotent consumer."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)


class BadEvent(Exception):
    """A message the worker cannot understand. Trying again will not help."""


def parse(value: bytes | None) -> dict[str, Any]:
    """The event in a Kafka message, or BadEvent."""
    try:
        data = json.loads(value or b"")
    except ValueError as error:
        raise BadEvent(f"not JSON: {error}") from None
    if not isinstance(data, dict) or not {"event_id", "type", "conversation_id"} <= data.keys():
        raise BadEvent("missing event_id, type or conversation_id")
    return data


def apply(session: Session, event: dict[str, Any]) -> bool:
    """Apply one event, inside the caller's transaction. False if it was applied before."""
    if session.get(ProcessedEvent, event["event_id"]) is not None:
        return False  # a repeat: Kafka delivered it again, and it changes nothing
    # Saved in the same transaction as the change: both are stored, or neither.
    session.add(ProcessedEvent(event_id=event["event_id"]))
    conversation_id = event["conversation_id"]
    row = session.get(UsageRow, conversation_id)
    if event["type"] == "message.created":
        if row is None:
            row = UsageRow(conversation_id=conversation_id, turns=0, chars=0)
            session.add(row)
        row.turns += 1
        row.chars += event.get("user_chars", 0) + event.get("reply_chars", 0)
    elif event["type"] == "conversation.deleted" and row is not None:
        session.delete(row)
    return True


def report(session: Session) -> list[tuple[str, int, int]]:
    """(conversation_id, turns, chars) for every conversation, busiest first."""
    rows = session.scalars(select(UsageRow).order_by(UsageRow.turns.desc()))
    return [(row.conversation_id, row.turns, row.chars) for row in rows]


def make_engine(url: str) -> Engine:
    """Connect, and create the tables if they are missing (derived data: no migrations)."""
    if url in ("sqlite://", "sqlite:///:memory:"):
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine
