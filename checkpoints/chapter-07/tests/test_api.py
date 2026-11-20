"""Tests for the HTTP API. TestClient calls the app directly: no server, no port, no network."""

import pytest
from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import ConfigError, Settings
from agent.llm import LLMError, MockClient

KEY = "test-key"
SETTINGS = Settings(
    model="test-model", mock=True, agent_name="agent", max_turns=2, api_key=None, agent_api_key=KEY
)
AUTH = {"X-API-Key": KEY}


@pytest.fixture
def client():
    """A fresh app, with fresh conversations, for every test."""
    return TestClient(create_app(SETTINGS, MockClient()))


def test_health_needs_no_key(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_starts_a_conversation(client):
    response = client.post("/chat", json={"message": "hello"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "[mock reply, turn 1] You said: hello"
    assert body["turns"] == 1
    assert body["conversation_id"]


def test_chat_continues_a_conversation(client):
    first = client.post("/chat", json={"message": "one"}, headers=AUTH).json()
    second = client.post(
        "/chat",
        json={"message": "שתיים", "conversation_id": first["conversation_id"]},
        headers=AUTH,
    ).json()
    assert second["conversation_id"] == first["conversation_id"]
    assert second["reply"] == "[mock reply, turn 2] You said: שתיים"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_chat_without_the_right_key_is_401(client, headers):
    response = client.post("/chat", json={"message": "hello"}, headers=headers)
    assert response.status_code == 401


@pytest.mark.parametrize("body", [{}, {"message": ""}, {"mesage": "hello"}, {"message": 42}])
def test_a_bad_body_is_422(client, body):
    response = client.post("/chat", json=body, headers=AUTH)
    assert response.status_code == 422


def test_unknown_conversation_is_404(client):
    response = client.post(
        "/chat", json={"message": "hello", "conversation_id": "nope"}, headers=AUTH
    )
    assert response.status_code == 404


class BrokenClient:
    def reply(self, messages):
        raise LLMError("Could not reach the API. Check your internet connection.")


def test_a_model_failure_is_502():
    client = TestClient(create_app(SETTINGS, BrokenClient()))
    response = client.post("/chat", json={"message": "hello"}, headers=AUTH)
    assert response.status_code == 502
    assert "Could not reach the API" in response.json()["detail"]


def test_the_server_refuses_to_start_without_a_key():
    no_key = Settings(model="m", mock=True, agent_name="a", max_turns=2, api_key=None)
    with pytest.raises(ConfigError, match="AGENT_API_KEY"):
        create_app(no_key, MockClient())


def test_the_chat_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'dir="rtl"' in response.text


def test_get_conversation_returns_its_messages(client):
    started = client.post("/chat", json={"message": "hello"}, headers=AUTH).json()
    response = client.get(f"/conversations/{started['conversation_id']}", headers=AUTH)
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello"
    assert response.json()["title"] == "hello"


def test_get_unknown_conversation_is_404(client):
    assert client.get("/conversations/nope", headers=AUTH).status_code == 404


def test_get_conversation_needs_the_key(client):
    started = client.post("/chat", json={"message": "hello"}, headers=AUTH).json()
    assert client.get(f"/conversations/{started['conversation_id']}").status_code == 401


def test_delete_forgets_the_conversation(client):
    started = client.post("/chat", json={"message": "hello"}, headers=AUTH).json()
    url = f"/conversations/{started['conversation_id']}"
    deleted = client.delete(url, headers=AUTH)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get(url, headers=AUTH).status_code == 404
    # Deleting twice: the second time there is nothing to delete.
    assert client.delete(url, headers=AUTH).status_code == 404


def test_list_shows_the_newest_conversations_first(client):
    client.post("/chat", json={"message": "first chat"}, headers=AUTH)
    client.post("/chat", json={"message": "second chat"}, headers=AUTH)
    response = client.get("/conversations", headers=AUTH)
    assert response.status_code == 200
    assert [c["title"] for c in response.json()] == ["second chat", "first chat"]


def test_list_needs_the_key(client):
    assert client.get("/conversations").status_code == 401
