"""Tests for the notes service's API. TestClient calls the app directly: no server, no port."""

import pytest
from fastapi.testclient import TestClient

from notes.api import create_app
from notes.config import Settings

KEY = "test-key"
AUTH = {"X-API-Key": KEY}
NOTE = {"conversation_id": "c1", "text": "buy milk"}


@pytest.fixture
def client():
    return TestClient(create_app(Settings(api_key=KEY)))


def test_a_note_is_saved_and_listed(client):
    created = client.post("/v1/notes", json=NOTE, headers=AUTH)
    assert created.status_code == 201
    listed = client.get("/v1/notes", params={"conversation_id": "c1"}, headers=AUTH).json()
    assert [note["text"] for note in listed] == ["buy milk"]
    assert client.get("/v1/notes", params={"conversation_id": "c2"}, headers=AUTH).json() == []


def test_search_and_get_and_delete(client):
    client.post("/v1/notes", json=NOTE, headers=AUTH)
    other = client.post("/v1/notes", json={**NOTE, "text": "call Dana"}, headers=AUTH).json()
    found = client.get("/v1/notes", params={"conversation_id": "c1", "q": "DANA"}, headers=AUTH)
    assert [note["id"] for note in found.json()] == [other["id"]]
    assert client.get(f"/v1/notes/{other['id']}", headers=AUTH).json()["text"] == "call Dana"
    assert client.delete(f"/v1/notes/{other['id']}", headers=AUTH).status_code == 204
    assert client.get(f"/v1/notes/{other['id']}", headers=AUTH).status_code == 404


def test_without_the_key_is_401(client):
    assert client.post("/v1/notes", json=NOTE).status_code == 401


def test_without_a_key_a_repeated_request_is_a_second_note(client):
    client.post("/v1/notes", json=NOTE, headers=AUTH)
    client.post("/v1/notes", json=NOTE, headers=AUTH)
    listed = client.get("/v1/notes", params={"conversation_id": "c1"}, headers=AUTH).json()
    assert len(listed) == 2


def test_the_same_idempotency_key_returns_the_first_note(client):
    headers = {**AUTH, "Idempotency-Key": "k1"}
    first = client.post("/v1/notes", json=NOTE, headers=headers)
    again = client.post("/v1/notes", json=NOTE, headers=headers)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    listed = client.get("/v1/notes", params={"conversation_id": "c1"}, headers=AUTH).json()
    assert len(listed) == 1


def test_the_same_key_for_another_note_is_409(client):
    headers = {**AUTH, "Idempotency-Key": "k1"}
    client.post("/v1/notes", json=NOTE, headers=headers)
    other = client.post("/v1/notes", json={**NOTE, "text": "sell milk"}, headers=headers)
    assert other.status_code == 409


def test_fail_after_save_saves_the_note():
    client = TestClient(create_app(Settings(api_key=KEY, fail_after_save=True)))
    assert client.post("/v1/notes", json=NOTE, headers=AUTH).status_code == 500
    listed = client.get("/v1/notes", params={"conversation_id": "c1"}, headers=AUTH).json()
    assert len(listed) == 1


def test_ready(client):
    assert client.get("/ready").json()["status"] == "ready"
