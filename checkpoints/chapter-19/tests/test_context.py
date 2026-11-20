"""Tests for the context: the budget, whole turns, compaction, and storing whole turns."""

from sqlalchemy import text

from agent.context import (
    STORED_RESULT_CHARS,
    SUMMARY_HEADER,
    build_context,
    estimate,
    shrink_result,
    split_turns,
)
from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import MockClient

SYSTEM = "Be brief."


def turn(question, answer):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


def tool_turn(question, answer):
    """A turn with one tool step in the middle: request, result, then the answer."""
    request = {"type": "tool_use", "id": "toolu_1", "name": "list_notes", "input": {}}
    result = {"type": "tool_result", "tool_use_id": "toolu_1", "content": "- [12345678] milk"}
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": [request]},
        {"role": "user", "content": [result]},
        {"role": "assistant", "content": answer},
    ]


def test_a_tool_step_stays_in_its_turn():
    history = turn("hi", "hello") + tool_turn("my notes?", "milk")
    turns = split_turns(history)
    assert [len(t) for t in turns] == [2, 4]


def test_the_newest_turns_that_fit_are_kept_and_the_budget_adds_up():
    history = turn("one " * 40, "a") + turn("two", "b") + turn("three", "c")
    question = {"role": "user", "content": "four"}
    # Room for the system prompt, the question and the two short turns, not the long one.
    two_short_turns = sum(estimate(m) for m in history[2:])
    limit = estimate(SYSTEM) + estimate([]) + estimate(question) + two_short_turns
    context = build_context(SYSTEM, [], history, question, limit, max_turns=10)
    assert [m["content"] for m in context.messages] == ["two", "b", "three", "c", "four"]
    assert (context.budget.kept, context.budget.dropped) == (2, 1)
    sent = sum(estimate(m) for m in context.messages)
    assert context.budget.total == estimate(SYSTEM) + estimate([]) + sent


def test_a_tool_request_is_never_sent_without_its_result():
    history = turn("hi", "hello") + tool_turn("my notes?", "milk")
    # Not enough room for the whole tool turn: it is left out whole, never cut inside.
    whole = sum(estimate(m) for m in history[2:])
    limit = estimate(SYSTEM) + estimate([]) + whole - 1
    context = build_context(SYSTEM, [], history, None, limit, max_turns=10)
    assert context.messages == []  # the newest turn did not fit, so nothing older is sent
    assert context.budget.dropped == 2


def test_the_summary_comes_first_and_is_not_a_question():
    context = build_context(SYSTEM, [], turn("two", "b"), None, 10_000, 10, summary="Dana.")
    assert context.messages[0]["content"] == f"{SUMMARY_HEADER}\nDana."
    assert context.budget.summary > 0


def test_a_long_tool_result_is_cut_when_it_is_stored():
    long = {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 5000}
    kept = shrink_result({"role": "user", "content": [long]})
    content = kept["content"][0]["content"]
    assert content.startswith("x" * STORED_RESULT_CHARS)
    assert "4000 more characters were cut" in content


def count(engine, sql):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def test_compaction_summarises_old_turns_and_keeps_them_stored():
    engine = make_engine("sqlite://")
    conversations = Conversations(MockClient(), 3, engine)  # at most 3 turns in a context
    conversation_id = conversations.start()
    conversations.send(conversation_id, "I am allergic to peanuts.")
    for message in ["two", "three", "four", "five"]:
        conversations.send(conversation_id, message)
    # The fifth message would have pushed the first turn out: it was summarised instead.
    toolbox = conversations.toolbox(conversation_id)
    context = conversations.context(conversation_id, toolbox)
    summary = context.messages[0]["content"]
    assert summary.startswith(SUMMARY_HEADER)
    assert "I am allergic to peanuts." in summary  # what the mock summary keeps
    assert count(engine, "SELECT COUNT(*) FROM summaries") == 1
    assert len(conversations.messages(conversation_id)) == 10  # nothing was deleted


def test_without_compaction_old_turns_are_simply_left_out():
    conversations = Conversations(MockClient(), 2, make_engine("sqlite://"), compact=False)
    conversation_id = conversations.start()
    for message in ["one", "two", "three"]:
        conversations.send(conversation_id, message)
    context = conversations.context(conversation_id, conversations.toolbox(conversation_id))
    assert context.messages[0]["content"] == "two"
    assert context.budget.dropped == 1


def test_the_whole_turn_is_stored_but_the_conversation_shows_text():
    engine = make_engine("sqlite://")
    conversations = Conversations(MockClient(), 10, engine, write_tools=True)
    conversation_id = conversations.start()
    conversations.send(conversation_id, "Keep in mind that I like tea.")
    kinds = count(engine, "SELECT GROUP_CONCAT(kind) FROM messages")
    assert kinds == "text,blocks,blocks,text"  # question, request, result, answer
    assert [m["role"] for m in conversations.messages(conversation_id)] == ["user", "assistant"]
    # The next call sends the tool step again: the model sees what it did.
    context = conversations.context(conversation_id, conversations.toolbox(conversation_id))
    assert context.messages[1]["content"][0]["name"] == "remember"
