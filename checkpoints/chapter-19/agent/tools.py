"""Tools: what the model may ask the program to do, kept as data in one registry.

A tool is a name, a description, an input model (a Pydantic class: its JSON schema is what
the model sees, and the same class checks what the model sent), the function that does the
work, and whether it writes. The model never runs a tool. It answers with a request to call
one; the agent loop (agent/loop.py) asks a Toolbox to run it, here, in our code.

The loop knows nothing about any particular tool: add a tool to the registry, and the loop,
the trace and the MCP server (agent/mcp_server.py) all have it.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from anthropic.types import ToolParam, ToolResultBlockParam, ToolUseBlock
from pydantic import BaseModel, ConfigDict, ValidationError

from agent.memory import MemoryStore
from agent.metrics import AGENT_TOOL_CALLS
from agent.notes import NotesClient

log = logging.getLogger(__name__)


class ToolError(Exception):
    """The tool could not do what was asked. The message goes back to the model, so it says
    how to recover."""


class ToolInput(BaseModel):
    """The base of every tool's input. A field the tool does not know is an error, not ignored."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    """What a tool works on, chosen by our code for one conversation. The model never sees it.

    What is None is not available in this run, and the tools that need it are not offered.
    """

    notes: NotesClient | None
    conversation_id: str
    memory: MemoryStore | None = None  # long-term memory and earlier conversations, one owner

    def notes_client(self) -> NotesClient:
        if self.notes is None:  # never offered without notes; this is only a safety net
            raise ToolError("There is no notes service in this run.")
        return self.notes

    def memory_store(self) -> MemoryStore:
        if self.memory is None:
            raise ToolError("There is no long-term memory in this run.")
        return self.memory


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # written for the model: what it does, when to call it, what comes back
    input_model: type[ToolInput]  # the input's JSON schema, and its validation
    run: Callable[[ToolContext, Any], str]  # our code: (context, validated input) -> text
    writes: bool = False  # it changes something; offered only when CHAT_WRITE_TOOLS=1
    needs: str | None = None  # "notes" or "memory": offered only when the run has it

    def schema(self) -> dict[str, Any]:
        """The input's JSON schema, without the titles Pydantic adds (noise for the model)."""
        schema: dict[str, Any] = without_titles(self.input_model.model_json_schema())
        return schema

    def param(self) -> ToolParam:
        """The tool as the API expects it in `tools`: everything except our code."""
        return {"name": self.name, "description": self.description, "input_schema": self.schema()}


def without_titles(schema: Any) -> Any:
    """Drop the "title" keys Pydantic puts on the schema and on every property."""
    if isinstance(schema, dict):
        return {key: without_titles(value) for key, value in schema.items() if key != "title"}
    if isinstance(schema, list):
        return [without_titles(item) for item in schema]
    return schema


def explain(name: str, error: ValidationError) -> str:
    """A validation error, in one line the model can act on."""
    problems = "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or 'input'}: {problem['msg']}"
        for problem in error.errors()
    )
    return f"Invalid input for {name}: {problems}. Fix the input and call {name} again."


@dataclass(frozen=True)
class Outcome:
    content: str  # what the model reads
    is_error: bool


class Toolbox:
    """The tools offered in one run, bound to one conversation. Running a tool never raises."""

    def __init__(self, tools: list[Tool], context: ToolContext) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.context = context

    def params(self) -> list[ToolParam]:
        return [tool.param() for tool in self.tools.values()]

    def call(self, name: str, tool_input: object) -> Outcome:
        """Validate the input, run the tool, and turn every failure into a result for the model."""
        tool = self.tools.get(name)
        try:
            if tool is None:
                known = ", ".join(self.tools) or "none"
                raise ToolError(f"There is no tool named {name!r}. The tools are: {known}.")
            try:  # the model wrote this input: check it before anything runs
                checked = tool.input_model.model_validate(tool_input)
            except ValidationError as error:
                raise ToolError(explain(name, error)) from None
            outcome = Outcome(tool.run(self.context, checked), False)
        except ToolError as error:  # an expected failure: the message is written for the model
            outcome = Outcome(str(error), True)
        except Exception:  # a bug in our tool: the details go to our log, not to the model
            log.exception("tool %s crashed", name)
            outcome = Outcome("The tool failed unexpectedly.", True)
        label = "error" if outcome.is_error else "ok"
        AGENT_TOOL_CALLS.labels(name if tool else "unknown", label).inc()
        log.log(
            logging.WARNING if outcome.is_error else logging.INFO,
            "tool %s: %s",
            name,
            label,
            extra={
                "tool": name,
                "outcome": label,
                "writes": bool(tool and tool.writes),  # a write is always in the log
                "conversation_id": self.context.conversation_id,
            },
        )
        return outcome

    def result(self, call: ToolUseBlock) -> ToolResultBlockParam:
        """One tool_use block from the model, answered with a tool_result block for it."""
        outcome = self.call(call.name, call.input)
        return {
            "type": "tool_result",
            "tool_use_id": call.id,
            "content": outcome.content,
            "is_error": outcome.is_error,
        }


class ToolRegistry:
    """Every tool the agent has, registered in one place."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"A tool named {tool.name!r} is already registered.")
        self._tools[tool.name] = tool
        return tool

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def toolbox(self, context: ToolContext, writes: bool = False) -> Toolbox:
        """The tools for one run. Writing tools only when `writes` is on (least privilege),
        and only the tools whose service this run has (`needs`)."""
        offered = [
            tool
            for tool in self
            if (writes or not tool.writes)
            and (tool.needs is None or getattr(context, tool.needs) is not None)
        ]
        return Toolbox(offered, context)
