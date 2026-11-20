"""Structured output: a conversation title as JSON, checked with Pydantic, with a fallback."""

import logging
from unittest.mock import Mock

import pytest

from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import ClaudeClient, LLMError, MockClient
from agent.titles import TitleSuggestion, suggest_title, title_schema

LONG = '[mock:json {"title": "' + "a very long title " * 4 + '", "topic": "code"}]'
BAD_TOPIC = '[mock:json {"title": "Oat milk", "topic": "groceries"}]'


def chat(*texts):
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"))
    conversation_id = conversations.start()
    for text in texts:
        conversations.send(conversation_id, text)
    return conversations, conversation_id


def test_a_valid_answer_becomes_the_title():
    conversations, conversation_id = chat("How do I read a traceback?")
    assert conversations.retitle(conversation_id) == ("mock title", "other")
    assert conversations.title(conversation_id) == "mock title"


def test_a_rejected_answer_gets_one_retry_with_the_reasons(caplog):
    conversations, conversation_id = chat(f"Plan my week {LONG}")
    assert conversations.retitle(conversation_id) == ("mock title", "other")  # the retry fit
    assert "title: String should have at most 50 characters" in caplog.text


def test_after_two_rejected_answers_the_automatic_title_stays(caplog):
    caplog.set_level(logging.WARNING)
    conversations, conversation_id = chat(f"Shopping {LONG} {BAD_TOPIC}")
    title, topic = conversations.retitle(conversation_id)
    assert topic is None
    assert title == 'Shopping [mock:json {"title": "a very long...'
    rejected = [r for r in caplog.records if r.getMessage().startswith("title suggestion")]
    assert [r.attempt for r in rejected] == [1, 2]
    assert "topic: Input should be 'code', 'work', 'study', 'personal' or 'other'" in caplog.text


def test_the_api_gets_a_schema_it_supports_and_pydantic_checks_the_rest():
    schema = title_schema()
    assert "maxLength" not in schema["properties"]["title"]  # the SDK moved it to the text
    with pytest.raises(ValueError):
        TitleSuggestion.model_validate_json('{"title": "' + "x" * 51 + '", "topic": "work"}')


def test_claude_client_asks_for_json_and_refuses_an_unfinished_answer():
    sdk = Mock()
    text = Mock(type="text", text='{"title": "Tracebacks", "topic": "code"}')
    sdk.messages.create.return_value = Mock(
        content=[text], stop_reason="end_turn", usage=Mock(input_tokens=5, output_tokens=9)
    )
    client = ClaudeClient("test-model", "Be brief.", sdk=sdk)

    answer = suggest_title(client, [{"role": "user", "content": "hi"}])

    assert answer == TitleSuggestion(title="Tracebacks", topic="code")
    output = sdk.messages.create.call_args.kwargs["output_config"]
    assert output["format"] == {"type": "json_schema", "schema": title_schema()}

    sdk.messages.create.return_value.stop_reason = "max_tokens"
    with pytest.raises(LLMError, match="did not finish its JSON answer"):
        client.reply_json([{"role": "user", "content": "hi"}], title_schema())
