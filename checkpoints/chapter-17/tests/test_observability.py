"""Request ids, JSON log lines and metrics: what chapter 13 promises, checked."""

import io
import json
import logging

import httpx2
import pytest
from fastapi.testclient import TestClient

from agent import logs
from agent.api import create_app
from agent.config import Settings
from agent.llm import MockClient
from agent.notes import NotesClient

KEY = "test-key"
SETTINGS = Settings(
    model="test-model",
    mock=True,
    agent_name="agent",
    max_turns=2,
    api_key=None,
    agent_api_key=KEY,
    metrics_token="metrics-token",
)
AUTH = {"X-API-Key": KEY}
METRICS = {"Authorization": "Bearer metrics-token"}


@pytest.fixture
def client():
    return TestClient(create_app(SETTINGS, MockClient()))


@pytest.fixture
def log_lines():
    """Every log line written during the test, parsed from JSON."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logs.JsonFormatter("test"))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    root.removeHandler(handler)
    root.setLevel(old_level)


def test_every_answer_carries_a_request_id(client):
    first = client.post("/chat", json={"message": "hello"}, headers=AUTH)
    second = client.post("/chat", json={"message": "hello"}, headers=AUTH)
    assert len(first.headers["X-Request-ID"]) == 32
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_an_id_from_the_caller_is_kept_if_it_looks_like_an_id(client):
    kept = client.get("/health", headers={"X-Request-ID": "abc-123"})
    replaced = client.get("/health", headers={"X-Request-ID": "two words\nand a newline"})
    assert kept.headers["X-Request-ID"] == "abc-123"
    assert replaced.headers["X-Request-ID"] != "two words\nand a newline"


def test_the_log_lines_of_a_request_share_its_id(client, log_lines):
    response = client.post("/chat", json={"message": "hello"}, headers=AUTH)
    request_id = response.headers["X-Request-ID"]
    mine = [line for line in log_lines() if line.get("request_id") == request_id]
    # The model's line and the access line, both with the id and as JSON.
    assert [line["message"] for line in mine] == ["model replied", "POST /chat 200"]
    assert mine[-1]["status"] == 200
    assert "duration_ms" in mine[-1]


def test_the_notes_client_passes_the_id_on():
    seen = []

    def handle(request):
        seen.append(request.headers.get("X-Request-ID"))
        return httpx2.Response(200, json=[])

    notes = NotesClient("http://notes", "k", transport=httpx2.MockTransport(handle))
    token = logs.request_id.set("req-42")
    try:
        notes.list("c1")
    finally:
        logs.request_id.reset(token)
    assert seen == ["req-42"]


def test_metrics_use_the_route_template_not_the_url(client, metric):
    before = metric(
        "http_requests_total", method="GET", route="/conversations/{conversation_id}", status="404"
    )
    client.get("/conversations/" + "0" * 32, headers=AUTH)
    page = client.get("/metrics", headers=METRICS).text
    assert "0" * 32 not in page
    after = metric(
        "http_requests_total", method="GET", route="/conversations/{conversation_id}", status="404"
    )
    assert after == before + 1


def test_what_people_write_never_reaches_the_logs(client, log_lines):
    # Exercise 5: messages and notes are the users' words. Counts and ids are fine.
    secret = "my password is hunter2"
    client.post("/chat", json={"message": secret}, headers=AUTH)
    assert log_lines()  # something was logged...
    leaked = [line["message"] for line in log_lines() if secret in json.dumps(line)]
    assert leaked == []  # ...but not what the user wrote
