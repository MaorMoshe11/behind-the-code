"""Tests for the team: router, orchestrator, subagents, parallel work, budget, verification."""

import json
import logging
import time
from unittest.mock import Mock

import httpx2

from agent import logs
from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import ClaudeClient, MockClient
from agent.notes import NotesClient
from agent.router import Router
from agent.team import (
    ORCHESTRATOR_PROMPT,
    REPORT_SCHEMA,
    SPECIALISTS,
    Budget,
    DelegateInput,
    Team,
)
from agent.tools import ToolContext

REVIEW = "Go over my notes and earlier conversations about the party and tell me what is open."


def notes_service(*texts):
    """A notes client whose service holds these notes, and searches them like the real one."""
    notes = [
        {"id": f"{n:08x}" + "0" * 24, "conversation_id": "c", "text": t, "created_at": "2026-11-19"}
        for n, t in enumerate(texts, start=0xA1B2C3D0)
    ]

    def handler(request):
        q = request.url.params.get("q", "").lower()
        return httpx2.Response(200, json=[note for note in notes if q in note["text"].lower()])

    return NotesClient("http://notes", "k", backoff=0, transport=httpx2.MockTransport(handler))


def make_team(delay=0.0, **limits):
    def client(prompt):
        return MockClient(prompt, delay)

    workers = {name: client(s.prompt) for name, s in SPECIALISTS.items()}
    return Team(Router(client("route")), client(ORCHESTRATOR_PROMPT), workers, **limits)


def chat(team, notes=None):
    """A conversation store with a team, an earlier conversation, and one memory."""
    conversations = Conversations(
        MockClient(), 10, make_engine("sqlite://"), notes, write_tools=True, team=team
    )
    earlier = conversations.start("dana")
    conversations.send(earlier, "The party is on March 3, we decided that.")
    conversations.memory("dana").remember("prefers short answers")
    return conversations, conversations.start("dana")


def test_the_router_sends_only_big_reviews_to_the_team(metric):
    router = Router(MockClient("route"))
    before = metric("routes_total", route="team")
    assert router.route(REVIEW) == "team"
    assert router.route("hello, how are you?") == "chat"
    assert metric("routes_total", route="team") == before + 1


def test_when_the_router_fails_the_chat_answers():
    broken = Mock()
    broken.reply_json.return_value = '{"route": "everyone"}'  # not a route we know
    assert Router(broken).route(REVIEW) == "chat"


def test_the_orchestrator_delegates_and_combines_and_only_text_is_stored():
    notes = notes_service("party: book the hall", "buy oat milk")
    conversations, current = chat(make_team(), notes)
    reply = conversations.send(current, REVIEW)

    assert "What the specialists found:" in reply
    assert "party: book the hall" in reply  # from the notes specialist
    assert "The party is on March 3" in reply  # from the memory specialist's search
    assert "oat milk" not in reply  # read by no one: the notes specialist searched "party"
    assert "short answers" not in reply  # read by the memory specialist, and left out
    stored = conversations.messages(current)
    assert [m["role"] for m in stored] == ["user", "assistant"]  # the question and the answer


def test_ordinary_messages_never_reach_the_team(metric):
    conversations, current = chat(make_team())
    before = metric("team_runs_total", outcome="done")
    assert "You said: hello" in conversations.send(current, "hello")
    assert metric("team_runs_total", outcome="done") == before


def test_a_specialist_gets_only_its_own_reading_tools():
    team = make_team()
    seen = {}
    real = team.workers["memory"].create

    def spy(messages, tools, schema=None):
        seen.setdefault("tools", [tool["name"] for tool in tools])
        seen.setdefault("brief", list(messages))  # its first call
        return real(messages, tools, schema)

    team.workers["memory"].create = spy
    conversations, current = chat(team, notes_service("party: hall"))
    conversations.send(current, REVIEW)

    assert seen["tools"] == ["recall", "search_conversations"]  # never remember or forget
    assert len(seen["brief"]) == 1  # a fresh context: the brief, and nothing else
    assert seen["brief"][0]["content"].startswith("Goal: Find what the user said about party")


def test_parallel_subagents_take_about_the_time_of_one():
    timings = {}
    for parallel in (True, False):
        conversations, current = chat(make_team(delay=0.2, parallel=parallel), notes_service("x"))
        start = time.perf_counter()
        conversations.send(current, REVIEW)
        timings[parallel] = time.perf_counter() - start
    # router + orchestrator + 2 subagent steps + orchestrator: 5 x 0.2 s in parallel,
    # 7 x 0.2 s one after the other.
    assert timings[True] < timings[False] - 0.25


def test_a_finding_no_tool_returned_is_kept_apart_as_unchecked():
    conversations, current = chat(make_team(), notes_service("party: hall"))
    reply = conversations.send(current, REVIEW + " [mock:invent]")

    assert "unchecked (no tool returned this source; not a fact):" in reply
    assert "- The party was moved to Friday. ([0badc0de])" in reply
    found = reply.split("unchecked")[0]
    assert "moved to Friday" not in found


def test_a_subagent_that_loops_is_stopped_and_reported():
    team = make_team(max_steps=3)
    context = ToolContext(notes_service("party: hall"), "c")
    brief = "Goal: Find the notes about party. [mock:loop]"
    result = team.run_specialist(SPECIALISTS["notes"], brief, context, Budget(20, 60000))

    assert (result.status, result.steps, result.report) == ("gave_up", 3, None)
    assert result.text().startswith("notes specialist: gave_up (model calls: 3, tool calls: 3")


def test_the_whole_run_stops_at_its_budget(metric):
    before = metric("team_runs_total", outcome="budget")
    conversations, current = chat(make_team(max_run_steps=2), notes_service("party: hall"))
    reply = conversations.send(current, REVIEW)

    assert reply.startswith("I stopped before finishing: the run made its 2 model calls.")
    assert metric("team_runs_total", outcome="budget") == before + 1


def test_the_budget_counts_every_agent_together():
    budget = Budget(max_steps=3, max_tokens=100)
    budget.before_call()
    budget.after_call("notes", 60)
    budget.before_call()
    budget.after_call("memory", 50)
    assert budget.by_agent == {"notes": 60, "memory": 50}
    try:
        budget.before_call()
    except Exception as error:
        assert "100 tokens" in str(error)
    else:
        raise AssertionError("a run over its tokens must stop")


def test_a_subagent_cannot_delegate():
    team = make_team()
    brief = "Goal: split this up. [mock:call delegate {}]"
    context = ToolContext(notes_service("party: hall"), "c")
    result = team.run_specialist(SPECIALISTS["notes"], brief, context, Budget(10, 10000))
    assert result.report is not None
    assert result.report.problems == [
        "There is no tool named 'delegate'. The tools are: list_notes."
    ]


class Lines(logging.Handler):
    """Every log line as the JSON formatter writes it, formatted in the thread that logs."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.setFormatter(logs.JsonFormatter("test"))
        self.lines = []

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


def test_one_request_id_and_an_agent_path_in_every_line_of_the_run():
    conversations, current = chat(make_team(), notes_service("party: hall"))
    lines = Lines()
    root = logging.getLogger()
    root.addHandler(lines)
    level = root.level
    root.setLevel(logging.INFO)  # setLevel, not .level =: it clears the loggers' caches
    try:
        conversations.send(current, REVIEW)
    finally:
        root.removeHandler(lines)
        root.setLevel(level)

    run = [line for line in lines.lines if "agent" in line]
    assert {line["agent"] for line in run} == {
        "orchestrator",
        "orchestrator/notes",
        "orchestrator/memory",
    }
    assert len({line["request_id"] for line in run}) == 1  # also in the subagents' threads
    assert logs.agent.get() is None and logs.request_id.get() is None  # reset after the run


def test_without_the_team_the_orchestrator_is_never_built():
    conversations, current = chat(None)
    assert conversations.team is None
    assert "You said: Go over" in conversations.send(current, REVIEW)


def test_a_weak_brief_still_reaches_the_subagent_and_says_what_is_missing():
    args = DelegateInput(specialist="notes", goal="look at the notes")
    assert args.brief() == "Goal: look at the notes\nContext: (none given)\nDone when: (not said)"


def test_the_real_client_asks_for_a_json_report_with_the_tools():
    sdk = Mock()
    sdk.messages.create.return_value = Mock(
        stop_reason="end_turn",
        content=[Mock(type="text", text="{}")],
        usage=Mock(input_tokens=1, output_tokens=1),
    )
    tools = [{"name": "list_notes", "description": "d", "input_schema": {"type": "object"}}]
    ClaudeClient("m", "p", sdk=sdk).create([{"role": "user", "content": "x"}], tools, REPORT_SCHEMA)

    sent = sdk.messages.create.call_args.kwargs
    assert sent["tools"] == tools
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": REPORT_SCHEMA}}
    assert json.dumps(REPORT_SCHEMA)  # plain JSON data


def test_the_orchestrator_reads_the_clock_itself_while_specialists_work():
    conversations, current = chat(make_team(), notes_service("party: hall"))
    reply = conversations.send(current, "Go over my notes about the party. What day is it?")

    assert "(UTC)" in reply  # current_time, called by the orchestrator
    assert "notes specialist: ok" in reply  # and the delegation, in the same step
