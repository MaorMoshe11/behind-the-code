"""Who may do what: keys per client, owners of conversations, /metrics, limits."""

import pytest
from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import ConfigError, Settings, load_settings
from agent.llm import MockClient
from agent.security import RateLimiter, hash_key, parse_clients

DANA_KEY, OMER_KEY = "dana-test-key", "omer-test-key"
SETTINGS = Settings(
    model="test-model",
    mock=True,
    agent_name="agent",
    max_turns=2,
    api_key=None,
    api_clients={hash_key(DANA_KEY): "dana", hash_key(OMER_KEY): "omer"},
    metrics_token="metrics-token",
)
DANA, OMER = {"X-API-Key": DANA_KEY}, {"X-API-Key": OMER_KEY}


@pytest.fixture
def client():
    return TestClient(create_app(SETTINGS, MockClient()))


def test_the_server_keeps_hashes_not_keys():
    entries = f"dana:{hash_key(DANA_KEY)},\nomer:{hash_key(OMER_KEY)}"
    assert parse_clients(entries) == {hash_key(DANA_KEY): "dana", hash_key(OMER_KEY): "omer"}
    assert DANA_KEY not in entries


def test_a_bad_entry_is_a_clear_error_that_shows_no_key(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEYS", f"dana:{DANA_KEY}")  # a key where the hash should be
    with pytest.raises(ConfigError, match="AGENT_API_KEYS") as error:
        load_settings()
    assert DANA_KEY not in str(error.value)


def test_one_client_cannot_touch_another_clients_conversation(client):
    mine = client.post("/chat", json={"message": "dana's secret"}, headers=DANA).json()
    path = f"/conversations/{mine['conversation_id']}"
    # 404, not 403: Omer cannot even learn that the conversation exists.
    assert client.get(path, headers=OMER).status_code == 404
    assert client.delete(path, headers=OMER).status_code == 404
    other = {"message": "hi", "conversation_id": mine["conversation_id"]}
    assert client.post("/chat", json=other, headers=OMER).status_code == 404
    assert client.get("/conversations", headers=OMER).json() == []
    assert client.get(path, headers=DANA).status_code == 200  # still there, for its owner


@pytest.mark.parametrize("bad_id", ["nope", "0" * 31, "Z" * 32, "../../etc/passwd"])
def test_a_malformed_conversation_id_is_422(client, bad_id):
    response = client.post("/chat", json={"message": "hi", "conversation_id": bad_id}, headers=DANA)
    assert response.status_code == 422


def test_a_huge_body_is_refused_before_it_is_read(client):
    response = client.post("/chat", content=b"x" * 100_000, headers=DANA)
    assert response.status_code == 413


def test_metrics_need_their_own_token(client):
    assert client.get("/metrics").status_code == 401
    assert (
        client.get("/metrics", headers={"Authorization": f"Bearer {DANA_KEY}"}).status_code == 401
    )
    page = client.get("/metrics", headers={"Authorization": "Bearer metrics-token"})
    assert page.status_code == 200
    assert "http_requests_total" in page.text


def test_without_a_token_there_are_no_metrics():
    settings = Settings(
        model="m", mock=True, agent_name="a", max_turns=2, api_key=None, agent_api_key="k"
    )
    assert TestClient(create_app(settings, MockClient())).get("/metrics").status_code == 404


def test_the_limiter_counts_per_client_and_per_window():
    now = [100.0]
    limiter = RateLimiter(limit=2, window=60, clock=lambda: now[0])
    assert limiter.check("dana") is None
    assert limiter.check("dana") is None
    assert limiter.check("dana") == 60  # the third in the same minute: wait for the window
    assert limiter.check("omer") is None  # another client has its own count
    now[0] += 45
    assert limiter.check("dana") == 15
    now[0] += 15
    assert limiter.check("dana") is None  # a new window


def test_too_many_messages_get_429_with_retry_after():
    settings = Settings(
        model="m", mock=True, agent_name="a", max_turns=2, api_key=None,
        api_clients=SETTINGS.api_clients, rate_limit=2,
    )  # fmt: skip
    client = TestClient(create_app(settings, MockClient()))
    for _ in range(2):
        assert client.post("/chat", json={"message": "hi"}, headers=DANA).status_code == 200
    refused = client.post("/chat", json={"message": "hi"}, headers=DANA)
    assert refused.status_code == 429
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert client.post("/chat", json={"message": "hi"}, headers=OMER).status_code == 200
