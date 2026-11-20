"""Tools: what the model may ask the program to do, kept as data in one registry.

A tool is a name, a description, an input model (a Pydantic class: its JSON schema is what
the model sees, and the same class checks what the model sent), the function that does the
work, and whether it writes. The model never runs a tool. It answers with a request to call
one; the agent loop (agent/loop.py) asks a Toolbox to run it, here, in our code.

The loop knows nothing about any particular tool: add a tool to the registry, and the loop,
the trace and the MCP server (agent/mcp_server.py) all have it.

Two defences against prompt injection live here, in Toolbox.call, the one place every call
goes through (chapter 21): what an untrusted tool returns is marked as data, and a writing
call needs a person's approval when every write does (CHAT_WRITE_TOOLS=ask) or when this run
has already read untrusted text.
"""

import logging
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any

from anthropic.types import ToolParam, ToolResultBlockParam, ToolUseBlock
from pydantic import BaseModel, ConfigDict, ValidationError

from agent import tracing
from agent.approvals import ApprovalNeeded, Approver, Request
from agent.memory import MemoryStore
from agent.metrics import AGENT_TOOL_CALLS, TOOL_APPROVALS
from agent.notes import NotesClient

NOT_APPROVED = (
    "The user did not approve this action, so it was not done. Do not try it again; tell "
    "the user what you wanted to do and why."
)
NOBODY = (
    "This action needs a person's approval, and nobody can approve it here, so it was not "
    "done. Tell the user what you wanted to do."
)

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
    writes: bool = False  # it changes something; offered only when CHAT_WRITE_TOOLS=1 or ask
    needs: str | None = None  # "notes" or "memory": offered only when the run has it
    # It returns text written by people or earlier conversations (notes, memories, messages):
    # data that may contain instructions addressed to the model.
    untrusted: bool = False
    # For a person who must approve a write: what it would change, computed by our code.
    preview: Callable[[ToolContext, Any], str] | None = None

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


def mark_untrusted(name: str, text: str) -> str:
    """Put an untrusted result between tags the system prompt explains: data, not orders.
    It helps a real model; it guarantees nothing (chapter 21)."""
    return f'<untrusted source="{name}">\n{text}\n</untrusted>'


class Toolbox:
    """The tools offered in one run, bound to one conversation. Running a tool never raises,
    except to pause the run for an approval over HTTP (ApprovalNeeded)."""

    def __init__(
        self,
        tools: list[Tool],
        context: ToolContext,
        parallel: bool = False,
        approver: Approver | None = None,
        ask: bool = False,
    ) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.context = context
        self.parallel = parallel  # may the calls of one step run at the same time?
        self.approver = approver  # who approves a write: the terminal, the API, or nobody
        self.ask = ask  # every write needs approval (CHAT_WRITE_TOOLS=ask)
        self.tainted = False  # this run has read untrusted text: writes need approval

    def params(self) -> list[ToolParam]:
        return [tool.param() for tool in self.tools.values()]

    def approve(self, tool: Tool, checked: ToolInput) -> str | None:
        """Ask a person, when this write needs one. None: go ahead. Raises ToolError when it
        must not run (rejected, or nobody to ask), and ApprovalNeeded to pause the run."""
        if not (self.ask or self.tainted):
            return None
        reason = "every write needs approval" if self.ask else "this run read untrusted text"
        preview = tool.preview(self.context, checked) if tool.preview else ""
        request = Request(tool.name, checked.model_dump(), preview, reason)
        if self.approver is None:
            TOOL_APPROVALS.labels(tool.name, "unattended").inc()
            raise ToolError(NOBODY)
        try:
            approved = self.approver(request)
        except ApprovalNeeded:
            TOOL_APPROVALS.labels(tool.name, "pending").inc()
            raise
        decision = "approved" if approved else "rejected"
        TOOL_APPROVALS.labels(tool.name, decision).inc()
        log.info("approval for %s: %s", tool.name, decision, extra={"reason": reason})
        if not approved:
            raise ToolError(NOT_APPROVED)
        return decision

    def call(self, name: str, tool_input: object, approved: bool = False) -> Outcome:
        """Validate the input, run the tool, and turn every failure into a result for the model.
        `approved`: a person already said yes to exactly this call (the HTTP approval)."""
        with tracing.span(f"tool {name}", "tool", input=tool_input) as span:
            outcome = self._call(name, tool_input, approved, span)
            span.outcome = "error" if outcome.is_error else "ok"
            return outcome

    def _call(self, name: str, tool_input: object, approved: bool, span: tracing.Span) -> Outcome:
        tool = self.tools.get(name)
        try:
            if tool is None:
                known = ", ".join(self.tools) or "none"
                raise ToolError(f"There is no tool named {name!r}. The tools are: {known}.")
            try:  # the model wrote this input: check it before anything runs
                checked = tool.input_model.model_validate(tool_input)
            except ValidationError as error:
                raise ToolError(explain(name, error)) from None
            if tool.writes:
                span.attrs["approval"] = "given" if approved else "not needed"
                if not approved:
                    try:
                        span.attrs["approval"] = self.approve(tool, checked) or "not needed"
                    except ApprovalNeeded:
                        span.attrs["approval"] = "pending"
                        span.outcome = "paused"
                        raise
                    except ToolError:
                        span.attrs["approval"] = "refused"
                        raise
            text = tool.run(self.context, checked)
            if tool.untrusted:
                self.tainted = True  # from now on, a write may have been chosen by this text
                text = mark_untrusted(name, text)
            outcome = Outcome(text, False)
        except ApprovalNeeded:
            raise  # not a failure: the run pauses (agent/loop.py), and a person decides
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

    def results(self, calls: list[ToolUseBlock]) -> list[ToolResultBlockParam]:
        """The results of one step's calls, in the order of the calls.

        At the same time (threads) only when this toolbox allows it and no call writes:
        two writes at once could interleave, and their order could matter. Each thread gets a
        copy of the context variables (the request id, the agent's name), so its log lines
        still say whose they are; a new thread would otherwise start without them.
        """
        known = [self.tools.get(call.name) for call in calls]
        if not self.parallel or len(calls) < 2 or any(t is None or t.writes for t in known):
            return [self.result(call) for call in calls]
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(copy_context().run, self.result, call) for call in calls]
            return [future.result() for future in futures]


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

    def toolbox(
        self,
        context: ToolContext,
        writes: bool = False,
        approver: Approver | None = None,
        ask: bool = False,
    ) -> Toolbox:
        """The tools for one run. Writing tools only when `writes` is on (least privilege),
        and only the tools whose service this run has (`needs`)."""
        offered = [
            tool
            for tool in self
            if (writes or not tool.writes)
            and (tool.needs is None or getattr(context, tool.needs) is not None)
        ]
        return Toolbox(offered, context, approver=approver, ask=ask)
