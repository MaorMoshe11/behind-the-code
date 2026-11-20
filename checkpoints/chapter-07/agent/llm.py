"""Clients that turn a conversation into a reply.

ClaudeClient talks to the real Claude API. MockClient returns fake replies,
costs nothing, and is the one the tests use.
"""

import logging
from typing import Protocol

import anthropic
from anthropic.types import MessageParam

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not answer. `fatal` means that trying again will not help."""

    def __init__(self, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class ChatClient(Protocol):
    """Anything that can answer a conversation."""

    def reply(self, messages: list[MessageParam]) -> str: ...


class ClaudeClient:
    """Sends the whole conversation to Claude and returns the reply text."""

    def __init__(
        self, model: str, system_prompt: str, sdk: anthropic.Anthropic | None = None
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        # Tests pass a fake SDK client here, so they never touch the network.
        self.sdk = sdk or anthropic.Anthropic()

    def reply(self, messages: list[MessageParam]) -> str:
        try:
            response = self.sdk.messages.create(
                model=self.model,
                max_tokens=16000,
                system=self.system_prompt,
                messages=messages,
            )
        except anthropic.AuthenticationError as error:
            raise LLMError(
                "The API rejected your key. Check ANTHROPIC_API_KEY.", fatal=True
            ) from error
        except anthropic.APIConnectionError as error:
            raise LLMError("Could not reach the API. Check your internet connection.") from error
        except anthropic.APIStatusError as error:
            raise LLMError(f"The API returned an error ({error.status_code}).") from error

        log.info(
            "reply from %s: %d input tokens, %d output tokens",
            self.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            return "(The model declined to answer this request.)"
        return "".join(block.text for block in response.content if block.type == "text")


class MockClient:
    """Returns a predictable fake reply. Free, offline, the same every time."""

    def reply(self, messages: list[MessageParam]) -> str:
        log.debug("mock reply to %d messages", len(messages))
        last_message = messages[-1]["content"]
        turn = (len(messages) + 1) // 2
        return f"[mock reply, turn {turn}] You said: {last_message}"
