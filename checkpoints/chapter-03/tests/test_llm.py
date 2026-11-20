"""Tests for agent.llm. None of them talks to the real API."""

import logging
from unittest.mock import Mock

import anthropic
import pytest

from agent.llm import ClaudeClient, LLMError, MockClient


def test_mock_client_repeats_the_last_message():
    reply = MockClient().reply([{"role": "user", "content": "hello"}])
    assert reply == "[mock reply, turn 1] You said: hello"


def test_claude_client_sends_the_conversation_and_joins_the_text():
    # A fake SDK client: it records every call and returns what we tell it to.
    sdk = Mock()
    sdk.messages.create.return_value = Mock(
        stop_reason="end_turn",
        content=[Mock(type="text", text="Hi "), Mock(type="text", text="there")],
    )
    client = ClaudeClient("test-model", "Be brief.", sdk=sdk)
    messages = [{"role": "user", "content": "hello"}]

    assert client.reply(messages) == "Hi there"

    sdk.messages.create.assert_called_once()
    sent = sdk.messages.create.call_args.kwargs
    assert sent["model"] == "test-model"
    assert sent["messages"] == messages


def test_connection_error_becomes_llm_error():
    sdk = Mock()
    # The SDK raises this when it cannot reach the server. Any stand-in request will do.
    sdk.messages.create.side_effect = anthropic.APIConnectionError(request=Mock())
    client = ClaudeClient("test-model", "Be brief.", sdk=sdk)

    with pytest.raises(LLMError) as caught:
        client.reply([{"role": "user", "content": "hello"}])

    assert "Could not reach the API" in str(caught.value)
    assert not caught.value.fatal


def test_rejected_key_is_fatal():
    sdk = Mock()
    sdk.messages.create.side_effect = anthropic.AuthenticationError(
        "invalid x-api-key", response=Mock(status_code=401), body=None
    )
    client = ClaudeClient("test-model", "Be brief.", sdk=sdk)

    with pytest.raises(LLMError) as caught:
        client.reply([{"role": "user", "content": "hello"}])

    assert caught.value.fatal
    # `raise ... from error` keeps the original error, for the log.
    assert isinstance(caught.value.__cause__, anthropic.AuthenticationError)


def test_token_counts_are_logged(caplog):
    caplog.set_level(logging.INFO)
    sdk = Mock()
    sdk.messages.create.return_value = Mock(
        stop_reason="end_turn",
        content=[Mock(type="text", text="Hi")],
        usage=Mock(input_tokens=12, output_tokens=3),
    )
    ClaudeClient("test-model", "Be brief.", sdk=sdk).reply([{"role": "user", "content": "hi"}])

    assert "12 input tokens, 3 output tokens" in caplog.text
