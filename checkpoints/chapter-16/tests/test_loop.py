"""Tests for the agent loop, with the scripted mock model and a fake notes service."""

import logging
from unittest.mock import Mock

import httpx2

from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import ClaudeClient, MockClient
from agent.loop import run_agent
from agent.notes import NotesClient
from agent.tools import Tool, notes_tool

NOTE = {
    "id": "n1",
    "conversation_id": "c1",
    "text": "buy oat milk",
    "created_at": "2026-11-19T10:00",
}


def fake_notes(*answers):
    """A NotesClient whose service gives these answers, in order, and the requests it got."""
    requests = []
    queue = list(answers)

    def handler(request):
        requests.append(request)
        return queue.pop(0)

    transport = httpx2.MockTransport(handler)
    return NotesClient("http://notes", "k", backoff=0, transport=transport), requests


def ask(text):
    return [{"role": "user", "content": text}]


def test_the_model_asks_for_the_tool_and_answers_with_its_result(metric):
    notes, requests = fake_notes(httpx2.Response(200, json=[NOTE]))
    before = metric("agent_tool_calls_total", tool="list_notes", outcome="ok")

    run = run_agent(
        MockClient(), ask("What did I save in my notes about milk?"), [notes_tool(notes, "c1")], 5
    )

    assert run.stop == "end_turn"
    assert (run.steps, run.tool_calls) == (2, 1)
    assert "- buy oat milk" in run.reply
    # The model chose the search; our code chose the conversation.
    assert requests[0].url.params["q"] == "milk"
    assert requests[0].url.params["conversation_id"] == "c1"
    # question, the model's tool request, our result, the final answer
    assert [m["role"] for m in run.messages] == ["user", "assistant", "user", "assistant"]
    request = run.messages[1]["content"][0]
    result = run.messages[2]["content"][0]
    assert request.type == "tool_use" and request.input == {"search": "milk"}
    assert result["tool_use_id"] == request.id and not result["is_error"]
    assert metric("agent_tool_calls_total", tool="list_notes", outcome="ok") == before + 1


def test_without_a_tool_request_the_loop_is_a_single_call():
    notes, requests = fake_notes()
    run = run_agent(MockClient(), ask("hello"), [notes_tool(notes, "c1")], 5)
    assert (run.stop, run.steps, run.tool_calls) == ("end_turn", 1, 0)
    assert run.reply == "[mock reply, turn 1] You said: hello"
    assert requests == []


def test_a_failing_tool_is_a_result_for_the_model_not_a_crash(metric):
    notes, _ = fake_notes(*[httpx2.Response(503)] * 3)  # down: one try and two retries
    before = metric("agent_tool_calls_total", tool="list_notes", outcome="error")

    run = run_agent(MockClient(), ask("What is in my notes?"), [notes_tool(notes, "c1")], 5)

    result = run.messages[2]["content"][0]
    assert result["is_error"]
    assert result["content"] == "The notes service is unavailable right now."
    assert run.stop == "end_turn"
    assert "the tool failed: The notes service is unavailable" in run.reply
    assert metric("agent_tool_calls_total", tool="list_notes", outcome="error") == before + 1


def test_a_wrong_input_is_refused_before_anything_runs():
    notes, requests = fake_notes()
    question = 'Notes? [mock:call list_notes {"search": 42}]'
    run = run_agent(MockClient(), ask(question), [notes_tool(notes, "c1")], 5)
    assert run.messages[2]["content"][0]["content"] == "search must be a string."
    assert requests == []


def test_the_model_cannot_choose_the_conversation():
    notes, requests = fake_notes()
    question = '[mock:call list_notes {"conversation_id": "someone-else"}]'
    run = run_agent(MockClient(), ask(question), [notes_tool(notes, "c1")], 5)
    assert run.messages[2]["content"][0]["content"] == "Unknown input field(s): conversation_id."
    assert requests == []


def test_an_unknown_tool_and_a_crashing_tool_are_results_too(caplog):
    def crash(tool_input):
        raise KeyError("a bug in our tool")

    broken = Tool("broken", "Always fails.", {"type": "object"}, crash)
    run = run_agent(MockClient(), ask("[mock:call broken {}]"), [broken], 5)
    assert run.messages[2]["content"][0]["content"] == "The tool failed unexpectedly."
    assert "tool broken crashed" in caplog.text  # the details are in our log only

    run = run_agent(MockClient(), ask("[mock:call delete_everything {}]"), [broken], 5)
    assert run.messages[2]["content"][0]["content"] == "There is no tool named 'delete_everything'."


def test_a_loop_that_never_ends_stops_at_max_steps(metric, caplog):
    caplog.set_level(logging.INFO)
    notes, requests = fake_notes(*[httpx2.Response(200, json=[NOTE])] * 3)
    before = metric("agent_runs_total", stop="max_steps")

    run = run_agent(MockClient(), ask("[mock:loop] my notes?"), [notes_tool(notes, "c1")], 3)

    assert (run.stop, run.steps, run.tool_calls) == ("max_steps", 3, 3)
    assert run.reply.startswith("I could not finish this in 3 steps")
    assert len(requests) == 3
    assert metric("agent_runs_total", stop="max_steps") == before + 1
    # One log line per step, and each step sends more than the one before.
    steps = [r for r in caplog.records if r.getMessage().startswith("agent step")]
    assert len(steps) == 3
    sent = [r.input_tokens for r in steps]
    assert sent == sorted(sent) and sent[0] < sent[-1]


def test_only_the_question_and_the_final_answer_are_saved():
    notes, _ = fake_notes(httpx2.Response(200, json=[NOTE]))
    conversations = Conversations(MockClient(), 10, make_engine("sqlite://"), notes, 5)
    conversation_id = conversations.start()

    reply = conversations.send(conversation_id, "What is in my notes?")

    assert conversations.messages(conversation_id) == [
        {"role": "user", "content": "What is in my notes?"},
        {"role": "assistant", "content": reply},
    ]


def test_claude_client_sends_the_tools_and_returns_the_whole_response():
    sdk = Mock()
    response = Mock(usage=Mock(input_tokens=5, output_tokens=2))
    sdk.messages.create.return_value = response
    notes, _ = fake_notes()
    tools = [notes_tool(notes, "c1").param()]

    assert ClaudeClient("test-model", "Be brief.", sdk=sdk).create(ask("hi"), tools) is response
    assert sdk.messages.create.call_args.kwargs["tools"] == tools
