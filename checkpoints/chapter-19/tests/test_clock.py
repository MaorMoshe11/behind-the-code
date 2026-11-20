"""current_time: one more tool, and nothing in the loop changed (exercise 3)."""

from datetime import UTC, datetime

from agent.clock import make_current_time
from agent.llm import MockClient
from agent.loop import run_agent
from agent.notes import NotesClient
from agent.notes_tools import TOOLS
from agent.tools import ToolContext, ToolRegistry

FIXED = datetime(2026, 11, 19, 21, 30, tzinfo=UTC)


def toolbox():
    registry = ToolRegistry()
    registry.register(make_current_time(lambda: FIXED))
    return registry.toolbox(ToolContext(NotesClient("http://notes", "k"), "c1"))


def test_the_model_asks_what_day_it_is():
    run = run_agent(MockClient(), [{"role": "user", "content": "What day is it?"}], toolbox(), 5)
    assert run.messages[1]["content"][0].name == "current_time"
    assert "Thursday 2026-11-19 21:30 (UTC)" in run.reply


def test_a_time_zone_from_the_list_and_only_from_it():
    tools = toolbox()
    assert tools.call("current_time", {"timezone": "Asia/Jerusalem"}).content == (
        "Thursday 2026-11-19 23:30 (Asia/Jerusalem)"
    )
    wrong = tools.call("current_time", {"timezone": "Mars/Base"})
    assert wrong.is_error and "Input should be 'UTC', 'Asia/Jerusalem'" in wrong.content


def test_it_is_registered_and_read_only():
    tool = next(tool for tool in TOOLS if tool.name == "current_time")
    assert not tool.writes
    assert tool.param()["input_schema"]["properties"]["timezone"]["enum"][0] == "UTC"
