"""A team of agents: an orchestrator that delegates, and specialists (subagents) that work.

The orchestrator is an agent loop (agent/loop.py) whose tool for work is `delegate` (it also
reads the clock itself, OWN_TOOLS). Delegating is a
tool call: our code starts a fresh loop for the specialist, with its own system prompt, its
own few tools from the registry (reading only), a context that holds nothing but the brief,
and a JSON report as its answer. The orchestrator gets back a short text, never the
specialist's whole conversation. Independent delegations of one step run at the same time.

One budget covers the whole run (every model call of every agent), one request id is in
every log line, and each line says which agent wrote it (logs.agent).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from anthropic.types import Message, MessageParam, ToolParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent import logs
from agent.config import Settings
from agent.llm import AgentClient, ClaudeClient, LLMError, MockClient, count
from agent.loop import run_agent
from agent.metrics import SUBAGENT_RUNS, TEAM_RUNS
from agent.notes_tools import TOOLS
from agent.router import ROUTER_PROMPT, Router
from agent.tools import Tool, Toolbox, ToolContext, ToolError, ToolInput, ToolRegistry

log = logging.getLogger(__name__)
SHOWN = 20  # findings in one report, at most: the orchestrator reads every one


# --- who is on the team ---------------------------------------------------------------

WORKER_RULES = (
    "You are a specialist working for an orchestrator, not talking to the user. You get one "
    "brief. Use your tools to do it, then answer with the report: the findings, each with the "
    "source your tool showed (a note's or a memory's [ref], or a conversation's date and "
    "title); what you looked for and did not find; and problems (a tool that failed, a brief "
    "that was unclear). Report only what your tools returned. You cannot ask questions: if the "
    "brief is unclear, do what you can and say what was unclear in problems."
)


@dataclass(frozen=True)
class Specialist:
    name: str
    does: str  # one line, for the orchestrator: when to delegate to it
    tools: tuple[str, ...]  # its tools, by name, from the registry: the fewest it needs
    prompt: str  # its system prompt


SPECIALISTS = {
    "notes": Specialist(
        "notes",
        "reads and searches the notes saved in this conversation",
        ("list_notes",),
        "You read the user's notes. " + WORKER_RULES,
    ),
    "memory": Specialist(
        "memory",
        "reads what is remembered about the user, and searches their earlier conversations",
        ("recall", "search_conversations"),
        "You read the user's long-term memory and earlier conversations. " + WORKER_RULES,
    ),
}

# Tools the orchestrator calls itself: small, read-only, and not worth a subagent (a whole
# loop, its prompt and its tokens, for one line of text).
OWN_TOOLS = ("current_time",)

ORCHESTRATOR_PROMPT = (
    "You coordinate specialists to answer the user. You cannot read notes, memories or "
    "conversations yourself: delegate each part of the work to the specialist that can do it. "
    "A specialist sees nothing but your brief, so give the goal, the context it needs (the "
    "user's words, names, dates) and when it is done. Delegate independent parts in the same "
    "response, so that they run at the same time. Then combine the reports into one short "
    "answer: use the findings, say what was not found and what failed, and never state an "
    "unchecked finding as a fact. Answer in the language the user writes in."
)


# --- the brief, and the report ----------------------------------------------------------


class DelegateInput(ToolInput):
    specialist: Literal["notes", "memory"]
    goal: str = Field(
        min_length=1, max_length=500, description="What to find, in one or two sentences."
    )
    context: str = Field(
        "",
        max_length=1000,
        description="What the specialist needs and cannot see: the user's words, names, "
        "dates, what is already known.",
    )
    done_when: str = Field(
        "", max_length=300, description="When the work is done: what the report must contain."
    )

    def brief(self) -> str:
        """The specialist's whole world: the first and only message it gets."""
        return (
            f"Goal: {self.goal}\nContext: {self.context or '(none given)'}\n"
            f"Done when: {self.done_when or '(not said)'}"
        )


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str
    source: str = Field(description="Where the tool showed it: a [ref], or a date and title.")


class Report(BaseModel):
    """What a specialist hands back: structured, short, and honest about gaps."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]
    not_found: list[str] = Field(description="What was looked for and not found.")
    problems: list[str] = Field(description="Tools that failed; what was unclear.")


REPORT_SCHEMA = anthropic.transform_schema(Report.model_json_schema())


@dataclass
class Result:
    """One subagent run, as our code saw it: the report, and how the run went."""

    specialist: str
    status: str  # ok, gave_up (step limit), no_report, budget, error, unavailable
    steps: int = 0
    tool_calls: int = 0
    tokens: int = 0
    seconds: float = 0.0
    report: Report | None = None
    unchecked: list[Finding] = field(default_factory=list)
    note: str = ""  # what went wrong, for the orchestrator

    def text(self) -> str:
        """The short text the orchestrator reads: a few lines, never the whole run."""
        lines = [
            f"{self.specialist} specialist: {self.status} (model calls: {self.steps}, "
            f"tool calls: {self.tool_calls}, tokens: {self.tokens}, {self.seconds:.1f} s)"
        ]
        if self.note:
            lines.append(self.note)
        if self.report:
            found = [line(f) for f in self.report.findings[:SHOWN]]
            lines += ["found:", *(found or ["- nothing"])]
            lines += [f"not found: {item}"[:200] for item in self.report.not_found]
            lines += [f"problem: {item}"[:200] for item in self.report.problems]
        if self.unchecked:
            lines.append("unchecked (no tool returned this source; not a fact):")
            lines += [line(f) for f in self.unchecked]
        return "\n".join(lines)


def line(finding: Finding) -> str:
    """One finding on one line: the fact cut to 150 characters, its source whole."""
    fact = finding.fact if len(finding.fact) <= 150 else finding.fact[:150] + "..."
    return f"- {fact} ({finding.source})"


def check(report: Report, run_messages: list[MessageParam]) -> tuple[Report, list[Finding]]:
    """Verify, do not trust: a finding stays only if its source appears in what the tools
    returned in this run. The others are set apart as unchecked."""
    returned = " ".join(
        str(block.get("content", ""))
        for message in run_messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    )
    kept = [f for f in report.findings if f.source.strip() and f.source.strip() in returned]
    unchecked = [f for f in report.findings if f not in kept]
    return report.model_copy(update={"findings": kept}), unchecked


# --- one budget for the whole run --------------------------------------------------------


class BudgetExceeded(Exception):
    """The team run used up its budget: no more model calls."""


class Budget:
    """Model calls, tokens and seconds for one team run, all agents together. Subagents run
    in threads and share it, so every change happens under a lock (shared state, chapter 6)."""

    def __init__(self, max_steps: int, max_tokens: int, max_seconds: float = 120.0) -> None:
        self.max_steps, self.max_tokens, self.max_seconds = max_steps, max_tokens, max_seconds
        self.started = time.monotonic()
        self.steps = 0
        self.tokens = 0
        self.by_agent: dict[str, int] = {}
        self.lock = threading.Lock()

    def before_call(self) -> None:
        with self.lock:
            if self.steps >= self.max_steps:
                raise BudgetExceeded(f"the run made its {self.max_steps} model calls")
            if self.tokens >= self.max_tokens:
                raise BudgetExceeded(f"the run used its {self.max_tokens} tokens")
            if time.monotonic() - self.started > self.max_seconds:
                raise BudgetExceeded(f"the run took more than {self.max_seconds:.0f} s")
            self.steps += 1

    def after_call(self, agent: str, tokens: int) -> None:
        with self.lock:
            self.tokens += tokens
            self.by_agent[agent] = self.by_agent.get(agent, 0) + tokens


class Metered:
    """A client that charges every call to the run's budget (checked before the call, so a
    run can go over its tokens by one call at most)."""

    def __init__(self, client: AgentClient, budget: Budget, agent: str) -> None:
        self.client, self.budget, self.agent = client, budget, agent
        self.tokens = 0  # this agent's tokens in this run
        self.calls = 0  # and its model calls, even when the run ends in the middle

    def create(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam],
        schema: dict[str, Any] | None = None,
    ) -> Message:
        self.budget.before_call()
        self.calls += 1
        if schema is None:
            response = self.client.create(messages, tools)
        else:
            response = self.client.create(messages, tools, schema)
        usage = response.usage
        tokens = sum(
            count(value)
            for value in (
                usage.input_tokens,
                usage.cache_read_input_tokens,
                usage.cache_creation_input_tokens,
                usage.output_tokens,
            )
        )
        self.tokens += tokens
        self.budget.after_call(self.agent, tokens)
        return response

    def reply(self, messages: list[MessageParam]) -> str:
        return self.client.reply(messages)

    def reply_json(self, messages: list[MessageParam], schema: dict[str, Any]) -> str:
        return self.client.reply_json(messages, schema)

    def count_tokens(self, messages: list[MessageParam], tools: list[ToolParam]) -> int:
        return self.client.count_tokens(messages, tools)


# --- the team ---------------------------------------------------------------------------


class Team:
    def __init__(
        self,
        router: Router,
        orchestrator: AgentClient,
        workers: dict[str, AgentClient],
        max_steps: int = 5,  # per agent, as CHAT_MAX_STEPS
        max_run_steps: int = 20,  # the whole run (CHAT_TEAM_MAX_STEPS)
        max_run_tokens: int = 60000,  # the whole run (CHAT_TEAM_MAX_TOKENS)
        parallel: bool = True,
        tools: ToolRegistry = TOOLS,
    ) -> None:
        self.router = router
        self.orchestrator = orchestrator
        self.workers = workers  # one client per specialist: its own system prompt and cache
        self.max_steps = max_steps
        self.limits = (max_run_steps, max_run_tokens)
        self.parallel = parallel
        self.tools = tools

    def wants(self, text: str) -> bool:
        return self.router.route(text) == "team"

    def delegate_tool(self, context: ToolContext, budget: Budget) -> Tool:
        """How the orchestrator hands out work. Its description lists the specialists."""
        roster = "; ".join(f"{s.name}: {s.does}" for s in SPECIALISTS.values())
        return Tool(
            name="delegate",
            description=(
                f"Give one part of the work to a specialist ({roster}). It sees only your "
                "brief and returns a short report. Call it several times in one response for "
                "independent parts: they run at the same time."
            ),
            input_model=DelegateInput,
            run=lambda _context, args: self.delegate(args, context, budget),
        )

    def answer(self, messages: list[MessageParam], context: ToolContext) -> str:
        """Run the orchestrator on the conversation (its words; the chat's tool steps are
        other tools, not its business) and return its answer."""
        budget = Budget(*self.limits)
        start = time.perf_counter()
        # One id for the whole run: the API sets one per request; the terminal has none.
        request = logs.request_id.set(logs.request_id.get() or logs.new_request_id())
        agent = logs.agent.set("orchestrator")
        try:
            own = [t for t in self.tools.toolbox(context).tools.values() if t.name in OWN_TOOLS]
            tools = [self.delegate_tool(context, budget), *own]
            toolbox = Toolbox(tools, context, self.parallel)
            words = [m for m in messages if isinstance(m["content"], str)]
            metered = Metered(self.orchestrator, budget, "orchestrator")
            try:
                run = run_agent(metered, words, toolbox, self.max_steps)
                outcome, reply = ("done" if run.stop == "end_turn" else run.stop), run.reply
            except BudgetExceeded as error:
                outcome = "budget"
                reply = f"I stopped before finishing: {error}. Ask for less at once."
            TEAM_RUNS.labels(outcome).inc()
            log.info(
                "team run finished: %s",
                outcome,
                extra={
                    "outcome": outcome,
                    "model_calls": budget.steps,
                    "tokens": budget.tokens,
                    "tokens_by_agent": dict(budget.by_agent),
                    "seconds": round(time.perf_counter() - start, 2),
                },
            )
            return reply
        finally:
            logs.agent.reset(agent)
            logs.request_id.reset(request)

    def delegate(self, args: DelegateInput, context: ToolContext, budget: Budget) -> str:
        result = self.run_specialist(SPECIALISTS[args.specialist], args.brief(), context, budget)
        SUBAGENT_RUNS.labels(result.specialist, result.status).inc()
        if result.status != "ok":
            raise ToolError(result.text())  # an error result: the orchestrator must notice
        return result.text()

    def run_specialist(
        self, specialist: Specialist, brief: str, context: ToolContext, budget: Budget
    ) -> Result:
        """A fresh loop: its own prompt and tools, nothing but the brief, a report back."""
        agent = logs.agent.set(f"orchestrator/{specialist.name}")  # the parent/child marker
        try:
            return self._run_specialist(specialist, brief, context, budget)
        finally:
            logs.agent.reset(agent)

    def _run_specialist(
        self, specialist: Specialist, brief: str, context: ToolContext, budget: Budget
    ) -> Result:
        start = time.perf_counter()
        metered = Metered(self.workers[specialist.name], budget, specialist.name)
        result = Result(specialist.name, "ok")
        try:
            # Least privilege: never the writing tools, and only this specialist's names.
            offered = self.tools.toolbox(context, writes=False).tools.values()
            toolbox = Toolbox([t for t in offered if t.name in specialist.tools], context)
            if not toolbox.tools:  # e.g. no notes service: do not pay for a model call
                result.status, result.note = "unavailable", "Its tools are not available here."
                return result
            log.info("subagent started", extra={"brief_chars": len(brief)})
            question: list[MessageParam] = [{"role": "user", "content": brief}]
            run = run_agent(metered, question, toolbox, self.max_steps, REPORT_SCHEMA)
            result.tool_calls = run.tool_calls
            if run.stop == "max_steps":
                result.status, result.note = "gave_up", f"It stopped after {run.steps} steps."
            else:
                try:
                    report = Report.model_validate_json(run.reply)
                    result.report, result.unchecked = check(report, run.messages)
                except ValidationError:
                    result.status, result.note = "no_report", f"Its answer: {run.reply[:200]}"
        except BudgetExceeded as error:
            result.status, result.note = "budget", f"Stopped: {error}."
        except LLMError as error:
            result.status, result.note = "error", f"The model call failed: {error}"
        result.steps, result.tokens = metered.calls, metered.tokens
        result.seconds = time.perf_counter() - start
        log.info(
            "subagent finished: %s",
            result.status,
            extra={"status": result.status, "tokens": result.tokens, "steps": result.steps},
        )
        return result


def make_team(settings: Settings) -> Team | None:
    """The team, when CHAT_TEAM=1. Each member is a client with its own system prompt; the
    subagents and the router use CHAT_WORKER_MODEL (the main model unless set)."""
    if not settings.team:
        return None

    def client(prompt: str, model: str) -> AgentClient:
        if settings.mock:
            return MockClient(prompt, settings.mock_delay)
        return ClaudeClient(model, prompt)

    return Team(
        Router(client(ROUTER_PROMPT, settings.worker_model)),
        client(ORCHESTRATOR_PROMPT, settings.model),
        {name: client(s.prompt, settings.worker_model) for name, s in SPECIALISTS.items()},
        settings.max_steps,
        settings.team_max_steps,
        settings.team_max_tokens,
        settings.team_parallel,
    )
