"""Tests for the agent loop, with the scripted mock model and a fake notes service."""

import logging
from unittest.mock import Mock

import httpx2

from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import ClaudeClient, MockClient
from agent.loop import run_agent
from agent.notes import NotesClient
from agent.notes_tools import TOOLS
from agent.tools import Tool, ToolContext, ToolInput, ToolRegistry

NOTE = {
    "id": "3f2a9c1b00000000000000000000000a",
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


def box(notes, writes=False):
    """The notes tools for conversation c1."""
    return TOOLS.toolbox(ToolContext(notes, "c1"), writes)


def ask(text):
    return [{"role": "user", "content": text}]


def test_the_model_asks_for_the_tool_and_answers_with_its_result(metric):
    notes, requests = fake_notes(httpx2.Response(200, json=[NOTE]))
    before = metric("agent_tool_calls_total", tool="list_notes", outcome="ok")

    run = run_agent(MockClient(), ask("What did I save in my notes about milk?"), box(notes), 5)

    assert run.stop == "end_turn"
    assert (run.steps, run.tool_calls) == (2, 1)
    assert "- [3f2a9c1b] buy oat milk" in run.reply
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
    run = run_agent(MockClient(), ask("hello"), box(notes), 5)
    assert (run.stop, run.steps, run.tool_calls) == ("end_turn", 1, 0)
    assert run.reply == "[mock reply, turn 1] You said: hello"
    assert requests == []


def test_two_calls_in_one_step_get_their_results_in_one_message():
    saved = [dict(NOTE, id=f"{n}" * 32, text=text) for n, text in ((1, "milk"), (2, "eggs"))]
    notes, requests = fake_notes(*[httpx2.Response(201, json=note) for note in saved])

    run = run_agent(
        MockClient(), ask("Remember that milk. Remember that eggs."), box(notes, True), 5
    )

    calls = run.messages[1]["content"]
    results = run.messages[2]["content"]
    assert [call.name for call in calls] == ["add_note", "add_note"]
    assert (run.steps, run.tool_calls) == (2, 2)
    assert run.messages[2]["role"] == "user" and len(results) == 2  # ONE message, both results
    assert [r["tool_use_id"] for r in results] == [call.id for call in calls]
    assert [r["content"] for r in results] == ["Saved: [11111111] milk", "Saved: [22222222] eggs"]
    assert len(requests) == 2


def test_a_failing_tool_is_a_result_for_the_model_not_a_crash(metric):
    notes, _ = fake_notes(*[httpx2.Response(503)] * 3)  # down: one try and two retries
    before = metric("agent_tool_calls_total", tool="list_notes", outcome="error")

    run = run_agent(MockClient(), ask("What is in my notes?"), box(notes), 5)

    result = run.messages[2]["content"][0]
    assert result["is_error"]
    assert result["content"].startswith("The notes service is unavailable right now.")
    assert run.stop == "end_turn"
    assert "the tool failed: The notes service is unavailable" in run.reply
    assert metric("agent_tool_calls_total", tool="list_notes", outcome="error") == before + 1


def test_a_wrong_input_is_refused_before_anything_runs():
    notes, requests = fake_notes()
    question = 'Notes? [mock:call list_notes {"search": 42}]'
    run = run_agent(MockClient(), ask(question), box(notes), 5)
    assert run.messages[2]["content"][0]["content"] == (
        "Invalid input for list_notes: search: Input should be a valid string. "
        "Fix the input and call list_notes again."
    )
    assert requests == []


def test_the_model_cannot_choose_the_conversation():
    notes, requests = fake_notes()
    question = '[mock:call list_notes {"conversation_id": "someone-else"}]'
    run = run_agent(MockClient(), ask(question), box(notes), 5)
    assert (
        "conversation_id: Extra inputs are not permitted"
        in run.messages[2]["content"][0]["content"]
    )
    assert requests == []


def test_an_unknown_tool_and_a_crashing_tool_are_results_too(caplog):
    def crash(context, args):
        raise KeyError("a bug in our tool")

    registry = ToolRegistry()
    registry.register(Tool("broken", "Always fails.", ToolInput, crash))
    tools = registry.toolbox(ToolContext(fake_notes()[0], "c1"))
    run = run_agent(MockClient(), ask("[mock:call broken {}]"), tools, 5)
    assert run.messages[2]["content"][0]["content"] == "The tool failed unexpectedly."
    assert "tool broken crashed" in caplog.text  # the details are in our log only

    run = run_agent(MockClient(), ask("[mock:call delete_everything {}]"), tools, 5)
    assert run.messages[2]["content"][0]["content"] == (
        "There is no tool named 'delete_everything'. The tools are: broken."
    )


def test_a_loop_that_never_ends_stops_at_max_steps(metric, caplog):
    caplog.set_level(logging.INFO)
    notes, requests = fake_notes(*[httpx2.Response(200, json=[NOTE])] * 3)
    before = metric("agent_runs_total", stop="max_steps")

    run = run_agent(MockClient(), ask("[mock:loop] my notes?"), box(notes), 3)

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
    tools = box(notes).params()

    assert ClaudeClient("test-model", "Be brief.", sdk=sdk).create(ask("hi"), tools) is response
    assert sdk.messages.create.call_args.kwargs["tools"] == tools
