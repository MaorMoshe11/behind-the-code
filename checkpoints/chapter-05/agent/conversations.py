"""The core of the agent: conversations and their messages.

The terminal chat and the HTTP API both use this module, so they behave the same.
Everything lives in memory: when the process stops, every conversation is gone.
"""

import logging
import uuid

from anthropic.types import MessageParam

from agent.history import trim_history
from agent.llm import ChatClient, LLMError

log = logging.getLogger(__name__)


class ConversationNotFound(Exception):
    """No conversation has this id (maybe the server restarted)."""


class Conversations:
    """Every open conversation, by id, and the one way to add a message to it."""

    def __init__(self, client: ChatClient, max_turns: int) -> None:
        self.client = client
        self.max_turns = max_turns
        self._messages: dict[str, list[MessageParam]] = {}

    def start(self) -> str:
        """Open a new, empty conversation and return its id."""
        conversation_id = uuid.uuid4().hex
        self._messages[conversation_id] = []
        return conversation_id

    def messages(self, conversation_id: str) -> list[MessageParam]:
        """The messages the agent still remembers in this conversation."""
        if conversation_id not in self._messages:
            raise ConversationNotFound(conversation_id)
        return self._messages[conversation_id]

    def send(self, conversation_id: str, text: str) -> str:
        """Add the user's message, get the model's reply, and remember both."""
        messages = self.messages(conversation_id)
        messages.append({"role": "user", "content": text})
        log.info("sending %d messages", len(messages))
        try:
            reply = self.client.reply(messages)
        except LLMError:
            messages.pop()  # forget the message that got no answer
            raise
        messages.append({"role": "assistant", "content": reply})
        # Keep only the last turns, so long chats do not get slow and expensive.
        self._messages[conversation_id] = trim_history(messages, self.max_turns)
        return reply

    def reset(self, conversation_id: str) -> None:
        """Forget every message in this conversation, but keep the conversation."""
        self.messages(conversation_id).clear()

    def delete(self, conversation_id: str) -> None:
        """Forget the conversation itself. Its id stops working."""
        self.messages(conversation_id)  # raises ConversationNotFound for an unknown id
        del self._messages[conversation_id]
