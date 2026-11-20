"""Tests for prompt caching: what the real client asks for, and the mock's cache numbers."""

from unittest.mock import Mock

from agent.llm import MIN_CACHE, ClaudeClient, MockClient
from agent.notes_tools import TOOLS
from agent.tools import ToolContext

QUESTION = [{"role": "user", "content": "hello"}]


def tools():
    return TOOLS.toolbox(ToolContext(None, "c1")).params()  # current_time only: small


def big_tools():
    return [{"name": f"tool_{n}", "description": "x" * 400, "input_schema": {}} for n in range(6)]


def test_the_real_client_asks_for_caching():
    sdk = Mock()
    sdk.messages.create.return_value = Mock(stop_reason="end_turn", content=[], usage=Mock())
    ClaudeClient("test-model", "Be brief.", sdk=sdk).create(QUESTION, tools())
    sent = sdk.messages.create.call_args.kwargs
    assert sent["cache_control"] == {"type": "ephemeral"}  # automatic: the last block
    assert sent["system"][-1]["cache_control"] == {"type": "ephemeral"}  # tools + system


def test_the_same_start_is_read_from_the_cache_the_second_time():
    client = MockClient()
    first = client.create(QUESTION, big_tools()).usage
    longer = [*QUESTION, {"role": "assistant", "content": "hi"}, {"role": "user", "content": "x"}]
    second = client.create(longer, big_tools()).usage
    assert first.cache_read_input_tokens == 0
    assert first.cache_creation_input_tokens >= MIN_CACHE
    assert second.cache_read_input_tokens == first.cache_creation_input_tokens
    assert second.cache_creation_input_tokens < 30  # only what was added
    assert second.input_tokens == 0


def test_a_changed_system_prompt_breaks_the_cache():
    morning, evening = MockClient("Be brief. It is 09:00."), MockClient("Be brief. It is 21:00.")
    evening.cache = morning.cache  # the same cache, as on the API
    morning.create(QUESTION, big_tools())
    after = evening.create(QUESTION, big_tools()).usage
    # The tools are first and unchanged, but the breakpoint is after the system prompt.
    assert after.cache_read_input_tokens == 0


def test_a_short_prompt_is_not_cached():
    client = MockClient()
    usage = client.create(QUESTION, tools()).usage
    assert usage.cache_creation_input_tokens == 0
    assert usage.input_tokens < MIN_CACHE


def test_count_tokens_asks_the_api():
    sdk = Mock()
    sdk.messages.count_tokens.return_value = Mock(input_tokens=321)
    assert ClaudeClient("test-model", "Be brief.", sdk=sdk).count_tokens(QUESTION, tools()) == 321
    assert sdk.messages.count_tokens.call_args.kwargs["model"] == "test-model"
