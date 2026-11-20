"""The delete saga: every step, and every compensation. A fake notes service, no network."""

import json

import httpx2
import pytest
from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import Settings
from agent.conversations import ConversationNotFound, Conversations
from agent.db import make_engine
from agent.llm import MockClient
from agent.notes import NotesClient, NotesUnavailable
from agent.saga import Step, delete_conversation, run_saga


class FakeNotesService:
    """Plays the notes service's /v1 API in memory. down=True: every request fails."""

    def __init__(self):
        self.notes = []  # dicts, like the service's JSON
        self.down = False
        self.counter = 0

    def handle(self, request):
        if self.down:
            raise httpx2.ConnectError("refused")
        conversation_id = request.url.params.get("conversation_id")
        if request.method == "DELETE":
            deleted = [n for n in self.notes if n["conversation_id"] == conversation_id]
            self.notes = [n for n in self.notes if n["conversation_id"] != conversation_id]
            return httpx2.Response(200, json=deleted)
        if request.method == "POST":
            self.counter += 1
            note = {**json.loads(request.content), "id": f"n{self.counter}"}
            self.notes.append(note)
            return httpx2.Response(201, json=note)
        return httpx2.Response(200, json=self.notes)

    def client(self):
        transport = httpx2.MockTransport(self.handle)
        return NotesClient("http://notes", "k", backoff=0, transport=transport)


@pytest.fixture
def world():
    """A conversation with one turn and two notes."""
    service = FakeNotesService()
    notes = service.client()
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"))
    conversation_id = conversations.start()
    conversations.send(conversation_id, "hello")
    notes.add(conversation_id, "buy milk")
    notes.add(conversation_id, "call Dana")
    return service, notes, conversations, conversation_id


def test_the_steps_are_compensated_newest_first_and_the_error_is_raised():
    calls = []

    def fail():
        raise RuntimeError("step 3 failed")

    steps = [
        Step("one", lambda: calls.append("one"), lambda: calls.append("undo one")),
        Step("two", lambda: calls.append("two"), lambda: calls.append("undo two")),
        Step("three", fail),
    ]
    with pytest.raises(RuntimeError, match="step 3 failed"):
        run_saga("test", steps)
    assert calls == ["one", "two", "undo two", "undo one"]


def test_the_happy_path_deletes_the_conversation_and_its_notes(world):
    service, notes, conversations, conversation_id = world
    run_saga("delete", delete_conversation(conversations, notes, conversation_id))
    assert service.notes == []
    with pytest.raises(ConversationNotFound):
        conversations.messages(conversation_id)


def test_notes_down_the_conversation_comes_back(world):
    service, notes, conversations, conversation_id = world
    service.down = True
    with pytest.raises(NotesUnavailable):
        run_saga("delete", delete_conversation(conversations, notes, conversation_id))
    assert len(conversations.messages(conversation_id)) == 2  # un-archived, untouched
    assert len(service.notes) == 2


def test_a_failure_after_the_notes_were_deleted_restores_them(world, monkeypatch):
    service, notes, conversations, conversation_id = world

    def broken_delete(conversation_id):
        raise RuntimeError("the chat's database is down")

    monkeypatch.setattr(conversations, "delete", broken_delete)
    with pytest.raises(RuntimeError):
        run_saga("delete", delete_conversation(conversations, notes, conversation_id))
    # Both compensations ran: the notes are back (new notes: new ids), and so is the chat.
    assert [note["text"] for note in service.notes] == ["buy milk", "call Dana"]
    assert [note["id"] for note in service.notes] == ["n3", "n4"]
    assert conversations.title(conversation_id) == "hello"


def test_the_api_answers_503_when_the_notes_are_down(monkeypatch):
    service = FakeNotesService()
    service.down = True
    monkeypatch.setattr("agent.api.make_notes", lambda settings: service.client())
    settings = Settings(
        model="m", mock=True, agent_name="agent", max_turns=2, api_key=None, agent_api_key="key"
    )
    app = TestClient(create_app(settings, MockClient()))
    auth = {"X-API-Key": "key"}
    conversation_id = app.post("/chat", json={"message": "hi"}, headers=auth).json()[
        "conversation_id"
    ]
    assert app.delete(f"/conversations/{conversation_id}", headers=auth).status_code == 503
    assert app.get(f"/conversations/{conversation_id}", headers=auth).status_code == 200
