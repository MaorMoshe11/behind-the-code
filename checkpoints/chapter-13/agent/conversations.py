"""The core of the agent: conversations and their messages.

The terminal chat and the HTTP API both use this module, so they behave the same.
Every message is saved in the database, so conversations survive a restart.
"""

import logging
import time
import uuid

from anthropic.types import MessageParam
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from agent.db import ConversationRow, MessageRow, now
from agent.history import trim_history
from agent.llm import ChatClient
from agent.metrics import LLM_SECONDS

log = logging.getLogger(__name__)
TITLE_LENGTH = 50  # a title is the start of the first message
NEW_TITLE = "New conversation"  # until the first message arrives
VISIBLE = ConversationRow.archived_at.is_(None)  # lists never show archived conversations


class ConversationNotFound(Exception):
    """No conversation has this id (it was deleted, or never existed)."""


def to_param(row: MessageRow) -> MessageParam:
    """A row from the database, in the shape the model client expects."""
    if row.role == "user":
        return {"role": "user", "content": row.content}
    return {"role": "assistant", "content": row.content}


class Conversations:
    """Every conversation, by id, and the one way to add a message to it."""

    def __init__(self, client: ChatClient, max_turns: int, engine: Engine) -> None:
        self.client = client
        self.max_turns = max_turns
        self.sessions = sessionmaker(engine)

    def _require(self, session: Session, conversation_id: str) -> ConversationRow:
        row = session.get(ConversationRow, conversation_id)
        if row is None or row.archived_at is not None:  # archived: hidden, as if deleted
            raise ConversationNotFound(conversation_id)
        return row

    def start(self) -> str:
        """Open a new, empty conversation and return its id."""
        conversation_id = uuid.uuid4().hex
        with self.sessions.begin() as session:
            session.add(ConversationRow(id=conversation_id, title=NEW_TITLE))
        return conversation_id

    def latest(self) -> str | None:
        """The id of the newest conversation, or None when there is none."""
        with self.sessions() as session:
            newest_first = select(ConversationRow.id).order_by(ConversationRow.created_at.desc())
            return session.scalar(newest_first.where(VISIBLE).limit(1))

    def newest(self, limit: int = 50) -> list[tuple[str, str]]:
        """(id, title) of the newest conversations, newest first."""
        with self.sessions() as session:
            rows = session.execute(
                select(ConversationRow.id, ConversationRow.title)
                .where(VISIBLE)
                .order_by(ConversationRow.created_at.desc())
                .limit(limit)
            )
            return [(row.id, row.title) for row in rows]

    def title(self, conversation_id: str) -> str:
        """The conversation's title: the start of its first message."""
        with self.sessions() as session:
            return self._require(session, conversation_id).title

    def messages(self, conversation_id: str) -> list[MessageParam]:
        """Every message in this conversation, oldest first."""
        with self.sessions() as session:
            self._require(session, conversation_id)
            rows = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.id)
            )
            return [to_param(row) for row in rows]

    def send(self, conversation_id: str, text: str) -> str:
        """Send the user's message with the recent history, and save both messages."""
        history = self.messages(conversation_id)
        # The model sees only the last turns; the database keeps all of them.
        prompt = trim_history(history, self.max_turns) + [{"role": "user", "content": text}]
        start = time.perf_counter()
        reply = self.client.reply(prompt)  # if this fails, nothing was saved
        seconds = time.perf_counter() - start
        LLM_SECONDS.observe(seconds)
        log.info(
            "model replied",
            extra={"messages": len(prompt), "llm_ms": round(seconds * 1000)},
        )
        # One transaction: both messages are saved, or neither is.
        with self.sessions.begin() as session:
            session.add(MessageRow(conversation_id=conversation_id, role="user", content=text))
            session.add(
                MessageRow(conversation_id=conversation_id, role="assistant", content=reply)
            )
            if not history:  # the first message names the conversation
                session.execute(
                    update(ConversationRow)
                    .where(ConversationRow.id == conversation_id)
                    .values(title=text[:TITLE_LENGTH])
                )
        return reply

    def reset(self, conversation_id: str) -> None:
        """Delete every message in this conversation, but keep the conversation."""
        with self.sessions.begin() as session:
            self._require(session, conversation_id)
            session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))

    def archive(self, conversation_id: str) -> None:
        """Hide the conversation: it is still stored, but works as if it were deleted."""
        with self.sessions.begin() as session:
            self._require(session, conversation_id).archived_at = now()

    def unarchive(self, conversation_id: str) -> None:
        """Undo archive(): the conversation is back, exactly as it was."""
        with self.sessions.begin() as session:
            session.execute(
                update(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .values(archived_at=None)
            )

    def delete(self, conversation_id: str) -> None:
        """Delete the conversation and its messages, archived or not. Its id stops working."""
        with self.sessions.begin() as session:
            if session.get(ConversationRow, conversation_id) is None:
                raise ConversationNotFound(conversation_id)
            session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))
            session.execute(delete(ConversationRow).where(ConversationRow.id == conversation_id))
