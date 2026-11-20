"""The chat publishes events. A list plays Kafka: no broker, no network."""

from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import Settings
from agent.events import make_events
from agent.llm import MockClient

KEY = "test-key"
SETTINGS = Settings(
    model="test-model", mock=True, agent_name="agent", max_turns=2, api_key=None, agent_api_key=KEY
)
AUTH = {"X-API-Key": KEY}


class FakeEvents:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


def test_a_reply_publishes_message_created():
    events = FakeEvents()
    client = TestClient(create_app(SETTINGS, MockClient(), events))
    body = client.post("/chat", json={"message": "hello"}, headers=AUTH).json()
    [event] = events.published
    assert event["type"] == "message.created"
    assert event["conversation_id"] == body["conversation_id"]
    assert event["user_chars"] == 5
    assert len(event["event_id"]) == 32


def test_deleting_publishes_conversation_deleted():
    events = FakeEvents()
    client = TestClient(create_app(SETTINGS, MockClient(), events))
    conversation_id = client.post("/chat", json={"message": "hi"}, headers=AUTH).json()[
        "conversation_id"
    ]
    assert client.delete(f"/conversations/{conversation_id}", headers=AUTH).status_code == 204
    assert [event["type"] for event in events.published] == [
        "message.created",
        "conversation.deleted",
    ]


def test_no_kafka_no_events():
    assert make_events(SETTINGS) is None  # off by default: tests and `uv run` need no Kafka
