"""Tests for the core with a real database: in memory, or a file in a temporary folder."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.conversations import ConversationNotFound, Conversations
from agent.db import MessageRow, make_engine, upgrade
from agent.llm import LLMError, MockClient


def test_a_conversation_survives_a_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"  # pytest gives every test its own empty folder
    upgrade(url)  # a file database gets its tables from the migrations, like agent.db
    first_run = make_engine(url)
    before = Conversations(MockClient(), 10, first_run)
    conversation_id = before.start()
    before.send(conversation_id, "remember me")
    first_run.dispose()  # close every connection, as a stopped server does

    second_run = make_engine(url)  # a new engine on the same file: a restarted server
    after = Conversations(MockClient(), 10, second_run)
    messages = after.messages(conversation_id)
    second_run.dispose()
    assert len(messages) == 2
    assert messages[0]["content"] == "remember me"


def test_everything_is_saved_but_the_model_sees_only_recent_turns():
    conversations = Conversations(MockClient(), 2, make_engine("sqlite://"))
    conversation_id = conversations.start()
    for message in ["one", "two", "three", "four"]:
        reply = conversations.send(conversation_id, message)
    # The mock counts the messages it was sent: two earlier turns plus the new message.
    assert reply == "[mock reply, turn 3] You said: four"
    assert len(conversations.messages(conversation_id)) == 8


class BrokenClient:
    def reply(self, messages):
        raise LLMError("Could not reach the API. Check your internet connection.")


def count_messages(engine):
    """Ask the database directly, with SQL, instead of trusting the code under test."""
    with engine.connect() as connection:
        return connection.execute(text("SELECT COUNT(*) FROM messages")).scalar_one()


def test_a_failed_reply_saves_nothing():
    engine = make_engine("sqlite://")
    conversations = Conversations(BrokenClient(), 10, engine)
    conversation_id = conversations.start()
    with pytest.raises(LLMError):
        conversations.send(conversation_id, "hello")
    assert count_messages(engine) == 0


def test_delete_removes_the_messages_too():
    engine = make_engine("sqlite://")
    conversations = Conversations(MockClient(), 10, engine)
    keep = conversations.start()
    conversations.send(keep, "keep me")
    gone = conversations.start()
    conversations.send(gone, "delete me")
    conversations.delete(gone)
    assert count_messages(engine) == 2
    with pytest.raises(ConversationNotFound):
        conversations.messages(gone)


def test_the_database_refuses_a_message_without_a_conversation():
    engine = make_engine("sqlite://")
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(MessageRow(conversation_id="nope", role="user", content="orphan"))


def test_the_first_message_names_the_conversation():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"))
    conversation_id = conversations.start()
    conversations.send(conversation_id, "plan a trip to the north " * 4)
    conversations.send(conversation_id, "and back")
    assert conversations.title(conversation_id) == "plan a trip to the north plan a trip to the..."


def test_an_archived_conversation_is_hidden_until_unarchived():
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"))
    conversation_id = conversations.start()
    conversations.archive(conversation_id)
    assert conversations.newest() == []
    with pytest.raises(ConversationNotFound):
        conversations.messages(conversation_id)
    conversations.unarchive(conversation_id)
    assert conversations.newest() == [(conversation_id, "New conversation")]
