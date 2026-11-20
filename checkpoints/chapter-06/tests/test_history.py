"""Tests for agent.history."""

import pytest
from anthropic.types import MessageParam

from agent.history import trim_history


def make_conversation(turns: int) -> list[MessageParam]:
    """Build a fake conversation: question 1, answer 1, question 2, answer 2, ..."""
    messages: list[MessageParam] = []
    for number in range(1, turns + 1):
        messages.append({"role": "user", "content": f"question {number}"})
        messages.append({"role": "assistant", "content": f"answer {number}"})
    return messages


def test_short_conversation_is_kept_whole():
    messages = make_conversation(turns=2)
    assert trim_history(messages, max_turns=3) == messages


def test_trim_keeps_the_last_whole_turns():
    # The test that would have caught the bug from chapter 1.
    messages = make_conversation(turns=5)
    trimmed = trim_history(messages, max_turns=3)
    assert len(trimmed) == 6
    assert trimmed[0] == {"role": "user", "content": "question 3"}
    assert trimmed[-1] == {"role": "assistant", "content": "answer 5"}


@pytest.mark.parametrize("turns", [0, 1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("max_turns", [1, 2, 3])
def test_trimmed_history_is_short_and_starts_with_user(turns, max_turns):
    trimmed = trim_history(make_conversation(turns), max_turns)
    assert len(trimmed) <= max_turns * 2
    if trimmed:
        assert trimmed[0]["role"] == "user"


def test_trim_before_the_reply_arrives():
    # Five questions, only four answers: the last question waits for its reply.
    messages = make_conversation(turns=4)
    messages.append({"role": "user", "content": "question 5"})
    trimmed = trim_history(messages, max_turns=2)
    assert trimmed[0]["role"] == "user"
    assert trimmed[-1] == {"role": "user", "content": "question 5"}


def test_zero_turns_is_an_error():
    with pytest.raises(ValueError):
        trim_history(make_conversation(turns=3), max_turns=0)
