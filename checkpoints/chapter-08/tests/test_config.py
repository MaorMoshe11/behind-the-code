"""Tests for agent.config."""

import pytest

from agent.config import ConfigError, load_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("CHAT_MAX_TURNS", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    settings = load_settings()
    assert settings.max_turns == 10
    assert settings.model == "claude-opus-5-5"


def test_max_turns_from_the_environment(monkeypatch):
    monkeypatch.setenv("CHAT_MAX_TURNS", "3")
    assert load_settings().max_turns == 3


@pytest.mark.parametrize("value", ["ten", "", "2.5", "0", "-4"])
def test_bad_max_turns_is_a_clear_error(monkeypatch, value):
    monkeypatch.setenv("CHAT_MAX_TURNS", value)
    with pytest.raises(ConfigError, match="CHAT_MAX_TURNS"):
        load_settings()
