"""The worker's logic, without Kafka: parse an event, apply it, report."""

import json

import pytest
from sqlalchemy.orm import sessionmaker

from worker.usage import BadEvent, apply, make_engine, parse, report


def created(event_id, conversation_id="c1", chars=10):
    return {
        "event_id": event_id,
        "type": "message.created",
        "conversation_id": conversation_id,
        "user_chars": chars,
        "reply_chars": 0,
    }


@pytest.fixture
def sessions():
    return sessionmaker(make_engine("sqlite://"))


def test_events_are_counted(sessions):
    with sessions.begin() as session:
        apply(session, created("e1"))
        apply(session, created("e2", chars=5))
        apply(session, created("e3", conversation_id="c2"))
    with sessions() as session:
        assert report(session) == [("c1", 2, 15), ("c2", 1, 10)]


def test_an_event_delivered_twice_is_counted_once(sessions):
    with sessions.begin() as session:
        assert apply(session, created("e1")) is True
    with sessions.begin() as session:  # the redelivery, after a crash before the commit
        assert apply(session, created("e1")) is False
    with sessions() as session:
        assert report(session) == [("c1", 1, 10)]


def test_a_deleted_conversation_leaves_the_statistics(sessions):
    with sessions.begin() as session:
        apply(session, created("e1"))
        apply(session, {"event_id": "e2", "type": "conversation.deleted", "conversation_id": "c1"})
    with sessions() as session:
        assert report(session) == []


@pytest.mark.parametrize("value", [b"not json", b"[1, 2]", json.dumps({"type": "x"}).encode()])
def test_a_bad_message_is_a_bad_event(value):
    with pytest.raises(BadEvent):
        parse(value)
