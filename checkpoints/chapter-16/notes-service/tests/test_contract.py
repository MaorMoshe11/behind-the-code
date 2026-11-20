"""The v1 contract: what clients (the chat service) rely on. Breaking it needs a /v2.

Adding is allowed: a new optional field in a request, a new field in an answer, a new
endpoint. Renaming, removing or changing the type of anything below is not.
"""

from fastapi.testclient import TestClient

from notes.api import create_app
from notes.config import Settings

AUTH = {"X-API-Key": "k"}


def test_v1_endpoints_are_still_there():
    paths = TestClient(create_app(Settings(api_key="k"))).get("/openapi.json").json()["paths"]
    assert set(paths["/v1/notes"]) >= {"get", "post", "delete"}
    assert set(paths["/v1/notes/{note_id}"]) >= {"get", "delete"}


def test_a_v1_note_keeps_its_fields():
    client = TestClient(create_app(Settings(api_key="k")))
    note = client.post("/v1/notes", json={"conversation_id": "c1", "text": "x"}, headers=AUTH)
    assert note.json().keys() >= {"id", "conversation_id", "text", "created_at"}
