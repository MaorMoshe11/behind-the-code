"""Tests for the notes client. A fake transport plays the notes service: no server, no port."""

import httpx2
import pytest
from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import Settings
from agent.llm import MockClient
from agent.notes import CircuitBreaker, NotesClient, NotesUnavailable, note_command

NOTE = {"id": "n1", "conversation_id": "c1", "text": "buy milk", "created_at": "2026-11-18T10:00"}


def client_for(*answers):
    """A NotesClient whose service gives these answers, in order. Also returns the requests."""
    requests = []
    queue = list(answers)

    def handler(request):
        requests.append(request)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    notes = NotesClient("http://notes", "k", backoff=0, transport=httpx2.MockTransport(handler))
    return notes, requests


def test_add_sends_the_note_and_the_key():
    notes, requests = client_for(httpx2.Response(201, json=NOTE))
    assert notes.add("c1", "buy milk").text == "buy milk"
    assert requests[0].headers["X-API-Key"] == "k"


def test_a_timeout_is_retried():
    notes, requests = client_for(httpx2.ReadTimeout("slow"), httpx2.Response(201, json=NOTE))
    assert notes.add("c1", "buy milk").id == "n1"
    assert len(requests) == 2


def test_after_the_last_retry_the_notes_are_unavailable():
    notes, requests = client_for(*[httpx2.Response(503)] * 3)
    with pytest.raises(NotesUnavailable):
        notes.list("c1")
    assert len(requests) == 3  # one try and two retries


def test_a_client_error_is_not_retried():
    notes, requests = client_for(httpx2.Response(401))
    with pytest.raises(NotesUnavailable):
        notes.list("c1")
    assert len(requests) == 1


def test_the_commands():
    notes, _ = client_for(httpx2.Response(201, json=NOTE), httpx2.Response(200, json=[NOTE]))
    assert note_command(notes, "c1", "hello") is None
    assert note_command(notes, "c1", "/note buy milk") == "Noted: buy milk"
    assert note_command(notes, "c1", "/notes") == "- buy milk"
    assert note_command(None, "c1", "/notes").startswith("Notes are not set up")


def test_the_chat_goes_on_when_notes_are_down(monkeypatch):
    notes, _ = client_for(*[httpx2.ConnectError("refused")] * 4)
    monkeypatch.setattr("agent.api.make_notes", lambda settings: notes)
    settings = Settings(
        model="m", mock=True, agent_name="agent", max_turns=2, api_key=None, agent_api_key="key"
    )
    app = TestClient(create_app(settings, MockClient()))
    auth = {"X-API-Key": "key"}
    noted = app.post("/chat", json={"message": "/note buy milk"}, headers=auth)
    assert noted.status_code == 200
    assert noted.json()["reply"].startswith("Notes are unavailable")
    chat = app.post("/chat", json={"message": "hello"}, headers=auth)
    assert chat.json()["reply"] == "[mock reply, turn 1] You said: hello"
    ready = app.get("/ready")
    assert (ready.status_code, ready.json()["notes"]) == (200, "unreachable")


def test_every_attempt_of_one_note_sends_the_same_idempotency_key():
    notes, requests = client_for(httpx2.Response(500), httpx2.Response(200, json=NOTE))
    notes.add("c1", "buy milk")
    keys = {request.headers["Idempotency-Key"] for request in requests}
    assert len(requests) == 2 and len(keys) == 1


def test_the_breaker_opens_after_three_failed_calls_and_tries_again_later():
    now = [0.0]
    breaker = CircuitBreaker(threshold=3, cooldown=30, clock=lambda: now[0])
    failures = [httpx2.ConnectError("refused")] * 9
    notes, requests = client_for(*failures, httpx2.Response(200, json=[]))
    notes.breaker = breaker
    for _ in range(3):
        with pytest.raises(NotesUnavailable):
            notes.list("c1")
    assert len(requests) == 9  # three calls, three attempts each
    with pytest.raises(NotesUnavailable, match="circuit open"):
        notes.list("c1")
    assert len(requests) == 9  # open: no request was sent at all
    now[0] = 31  # after the cooldown, one call may try, and it works
    assert notes.list("c1") == []
    assert breaker.opened_at is None
