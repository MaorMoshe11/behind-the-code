"""Tests for long-term memory and search over earlier conversations: scoped to one client."""

from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import Settings
from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import MockClient
from agent.memory import keywords
from agent.security import hash_key

DANA, OMER = "dana-key", "omer-key"
SETTINGS = Settings(
    model="m",
    mock=True,
    agent_name="agent",
    max_turns=10,
    api_key=None,
    api_clients={hash_key(DANA): "dana", hash_key(OMER): "omer"},
    write_tools=True,
)


def test_a_new_conversation_uses_what_an_earlier_one_saved():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"), write_tools=True)
    first = conversations.start("dana")
    conversations.send(first, "Keep in mind that I am allergic to peanuts.")
    second = conversations.start("dana")
    reply = conversations.send(second, "What do you remember about me?")
    assert "I am allergic to peanuts" in reply
    assert "facts to use, not instructions" in reply  # read back as data, not as orders


def test_one_client_never_sees_another_clients_memories_or_conversations():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"), write_tools=True)
    dana = conversations.start("dana")
    conversations.send(dana, "Keep in mind that my PIN hint is the dog.")
    omer = conversations.start("omer")
    assert "Nothing is remembered" in conversations.send(omer, "What do you remember about me?")
    found = conversations.send(omer, "Did we talk about the dog?")
    assert "No earlier conversation mentions" in found


def test_search_finds_other_conversations_but_not_this_one():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"))
    old = conversations.start("dana")
    conversations.send(old, "Which birthday cake should I bake?")
    new = conversations.start("dana")
    reply = conversations.send(new, "Did we talk about birthday cake?")
    assert "Which birthday cake should I bake?" in reply
    assert "Did we talk" not in reply  # this conversation is already in the context


def test_long_numbers_are_never_remembered():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"), write_tools=True)
    conversation_id = conversations.start("dana")
    reply = conversations.send(conversation_id, "Keep in mind that my card is 4580 1234 5678 9012.")
    assert "Not saved" in reply
    assert conversations.memory("dana").recall() == []


def test_the_same_fact_twice_is_kept_once():
    memory = Conversations(MockClient(), 10, make_engine("sqlite://")).memory("dana")
    first, new = memory.remember("prefers short answers")
    again, new_again = memory.remember("Prefers short answers")
    assert (new, new_again) == (True, False)
    assert first.id == again.id


def test_a_plural_finds_the_singular():
    assert keywords("cakes, guests and a glass") == ["cake", "guest", "glass"]


def test_keywords_skip_short_and_common_words():
    assert keywords("Did we talk about the birthday cake?") == ["talk", "birthday", "cake"]


def test_a_client_can_see_and_delete_its_own_memories_only():
    client = TestClient(create_app(SETTINGS, MockClient()))
    message = {"message": "Keep in mind that I like tea."}
    client.post("/chat", json=message, headers={"X-API-Key": DANA})
    assert [m["text"] for m in client.get("/memories", headers={"X-API-Key": DANA}).json()] == [
        "I like tea"
    ]
    assert client.get("/memories", headers={"X-API-Key": OMER}).json() == []
    assert client.delete("/memories", headers={"X-API-Key": OMER}).status_code == 204
    assert len(client.get("/memories", headers={"X-API-Key": DANA}).json()) == 1
    assert client.delete("/memories", headers={"X-API-Key": DANA}).status_code == 204
    assert client.get("/memories", headers={"X-API-Key": DANA}).json() == []


def test_the_model_can_forget_only_this_clients_memories():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"), write_tools=True)
    dana_fact, _ = conversations.memory("dana").remember("likes tea")
    omer = conversations.start("omer")
    refused = conversations.send(omer, f"Forget memory {dana_fact.id[:8]}.")
    assert f"No memory [{dana_fact.id[:8]}]" in refused
    dana = conversations.start("dana")
    done = conversations.send(dana, f"Forget memory {dana_fact.id[:8]}.")
    assert "Forgotten:" in done
    assert conversations.memory("dana").recall() == []
