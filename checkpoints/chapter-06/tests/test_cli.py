"""Integration tests: the whole chat loop, with the mock client."""

from dataclasses import replace

from agent.cli import chat_loop
from agent.config import Settings
from agent.llm import LLMError, MockClient

SETTINGS = Settings(model="test-model", mock=True, agent_name="agent", max_turns=2, api_key=None)


def type_lines(monkeypatch, *lines):
    """Make input() return these lines one by one, as if a user typed them."""
    answers = iter(lines)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))


def test_a_short_conversation(monkeypatch, capsys):
    type_lines(monkeypatch, "hello", "how are you", "exit")
    chat_loop(MockClient(), SETTINGS)
    output = capsys.readouterr().out
    assert "agent> [mock reply, turn 1] You said: hello" in output
    assert "agent> [mock reply, turn 2] You said: how are you" in output
    assert output.endswith("Bye!\n")


def test_long_conversation_is_trimmed(monkeypatch, capsys):
    type_lines(monkeypatch, "one", "two", "three", "four", "exit")
    chat_loop(MockClient(), SETTINGS)
    output = capsys.readouterr().out
    # max_turns is 2: the model sees two earlier turns plus the new message.
    assert "[mock reply, turn 3] You said: three" in output
    assert "[mock reply, turn 3] You said: four" in output


class BrokenClient:
    """A fake client whose every request fails, like an API that cannot be reached."""

    def reply(self, messages):
        raise LLMError("Could not reach the API. Check your internet connection.")


def test_a_failed_request_does_not_end_the_chat(monkeypatch, capsys):
    type_lines(monkeypatch, "hello", "exit")
    chat_loop(BrokenClient(), SETTINGS)
    output = capsys.readouterr().out
    assert "Could not reach the API." in output
    assert output.endswith("Bye!\n")


def test_reset_starts_a_new_conversation(monkeypatch, capsys):
    type_lines(monkeypatch, "one", "two", "/reset", "three", "exit")
    chat_loop(MockClient(), SETTINGS)
    output = capsys.readouterr().out
    assert "Conversation cleared. Starting over." in output
    # After /reset the mock sees only the new message, so it counts from 1 again.
    assert "[mock reply, turn 1] You said: three" in output


def test_history_counts_turns_not_messages(monkeypatch, capsys):
    type_lines(monkeypatch, "/history", "one", "two", "/history", "exit")
    chat_loop(MockClient(), SETTINGS)
    output = capsys.readouterr().out
    assert "0 turns in memory." in output
    # Two questions and two answers are four messages, but two turns.
    assert "2 turns in memory." in output


def test_continue_picks_up_the_last_conversation(monkeypatch, capsys, tmp_path):
    settings = replace(SETTINGS, database_url=f"sqlite:///{tmp_path / 'test.db'}")
    type_lines(monkeypatch, "one", "two", "exit")
    chat_loop(MockClient(), settings)
    type_lines(monkeypatch, "three", "exit")
    chat_loop(MockClient(), settings, resume=True)
    output = capsys.readouterr().out
    assert "Continuing the last conversation (2 turns)." in output
    assert "[mock reply, turn 3] You said: three" in output
