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


def test_a_secret_can_come_from_a_file(monkeypatch, tmp_path):
    # How secret stores hand secrets to a container: a file, and its path in NAME_FILE.
    secret = tmp_path / "agent_api_key.txt"
    secret.write_text("from-the-file\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_API_KEY", "from-the-variable")
    monkeypatch.setenv("AGENT_API_KEY_FILE", str(secret))
    assert load_settings().agent_api_key == "from-the-file"


def test_a_missing_secret_file_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_API_KEY_FILE", str(tmp_path / "nope.txt"))
    with pytest.raises(ConfigError, match="AGENT_API_KEY_FILE"):
        load_settings()


def test_the_database_password_is_a_separate_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://agent@db:5432/agent")
    monkeypatch.setenv("DATABASE_PASSWORD", "s3cret")
    assert load_settings().database_url == "postgresql+psycopg://agent:s3cret@db:5432/agent"


@pytest.mark.parametrize("app_env", ["production", "Prod", ""])
def test_an_unknown_environment_is_a_clear_error(monkeypatch, app_env):
    monkeypatch.setenv("APP_ENV", app_env)
    with pytest.raises(ConfigError, match="APP_ENV"):
        load_settings()


def test_outside_local_the_database_must_be_given(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_settings()
