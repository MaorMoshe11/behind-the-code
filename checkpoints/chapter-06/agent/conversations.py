"""The core of the agent: conversations and their messages.

The terminal chat and the HTTP API both use this module, so they behave the same.
Every message is saved in the database, so conversations survive a restart.
"""

import logging
import uuid

from anthropic.types import MessageParam
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from agent.db import ConversationRow, MessageRow
from agent.history import trim_history
from agent.llm import ChatClient

log = logging.getLogger(__name__)


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

    def _require(self, session: Session, conversation_id: str) -> None:
        if session.get(ConversationRow, conversation_id) is None:
            raise ConversationNotFound(conversation_id)

    def start(self) -> str:
        """Open a new, empty conversation and return its id."""
        conversation_id = uuid.uuid4().hex
        with self.sessions.begin() as session:
            session.add(ConversationRow(id=conversation_id))
        return conversation_id

    def latest(self) -> str | None:
        """The id of the newest conversation, or None when there is none."""
        with self.sessions() as session:
            newest_first = select(ConversationRow.id).order_by(ConversationRow.created_at.desc())
            return session.scalar(newest_first.limit(1))

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
        log.info("sending %d messages", len(prompt))
        reply = self.client.reply(prompt)  # if this fails, nothing was saved
        # One transaction: both messages are saved, or neither is.
        with self.sessions.begin() as session:
            session.add(MessageRow(conversation_id=conversation_id, role="user", content=text))
            session.add(
                MessageRow(conversation_id=conversation_id, role="assistant", content=reply)
            )
        return reply

    def reset(self, conversation_id: str) -> None:
        """Delete every message in this conversation, but keep the conversation."""
        with self.sessions.begin() as session:
            self._require(session, conversation_id)
            session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))

    def delete(self, conversation_id: str) -> None:
        """Delete the conversation and its messages. Its id stops working."""
        with self.sessions.begin() as session:
            self._require(session, conversation_id)
            session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))
            session.execute(delete(ConversationRow).where(ConversationRow.id == conversation_id))
