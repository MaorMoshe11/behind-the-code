"""Clients that turn a conversation into a reply.

ClaudeClient talks to the real Claude API. MockClient returns fake replies,
costs nothing, and is the one the tests use.
"""

import logging
from typing import Protocol

import anthropic
from anthropic.types import MessageParam

from agent.metrics import LLM_ERRORS, LLM_TOKENS

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
        # Most specific first: each reason gets its own message and its own metric label,
        # so a graph can tell "our key is wrong" from "the network is down".
        except anthropic.AuthenticationError as error:
            LLM_ERRORS.labels("auth").inc()
            raise LLMError(
                "The API rejected your key. Check ANTHROPIC_API_KEY.", fatal=True
            ) from error
        except anthropic.RateLimitError as error:
            LLM_ERRORS.labels("rate_limited").inc()
            raise LLMError("Too many requests to the API. Wait a minute and try again.") from error
        except anthropic.APIStatusError as error:
            LLM_ERRORS.labels("status").inc()
            raise LLMError(f"The API returned an error ({error.status_code}).") from error
        except anthropic.APITimeoutError as error:  # a kind of APIConnectionError: first
            LLM_ERRORS.labels("timeout").inc()
            raise LLMError("The API did not answer in time. Try again.") from error
        except anthropic.APIConnectionError as error:
            LLM_ERRORS.labels("connection").inc()
            raise LLMError("Could not reach the API. Check your internet connection.") from error

        usage = response.usage
        LLM_TOKENS.labels("input").inc(usage.input_tokens)
        LLM_TOKENS.labels("output").inc(usage.output_tokens)
        log.info(
            "reply from %s: %d input tokens, %d output tokens",
            self.model,
            usage.input_tokens,
            usage.output_tokens,
            # Anthropic's own id for this call: what their support asks for.
            extra={"api_request_id": response._request_id},
        )
        if response.stop_reason == "refusal":
            return "(The model declined to answer this request.)"
        return "".join(block.text for block in response.content if block.type == "text")


def mock_tokens(text: str) -> int:
    """A made-up but steady token count: about one token per four characters."""
    return len(text) // 4 + 1


class MockClient:
    """Returns a predictable fake reply. Free, offline, the same every time."""

    def reply(self, messages: list[MessageParam]) -> str:
        last_message = messages[-1]["content"]
        turn = (len(messages) + 1) // 2
        reply = f"[mock reply, turn {turn}] You said: {last_message}"
        # Report usage like the real client does, so the token metrics work offline too.
        sent = mock_tokens("".join(str(message["content"]) for message in messages))
        LLM_TOKENS.labels("input").inc(sent)
        LLM_TOKENS.labels("output").inc(mock_tokens(reply))
        log.debug("mock reply: %d input tokens, %d output tokens", sent, mock_tokens(reply))
        return reply
