"""Graders: what decides whether one run of one case passed.

Code graders check facts our code can see: the answer's text, the trajectory (which tools
were called, with what input, how many model calls), and the state of the world afterwards
(what is in the notes and the memory). They are exact, free and the same every time.

The judge is a model that grades an answer against a rubric written in words, for what code
cannot check ("the answer says what is still open, and nothing more"). It is itself a model:
it is checked against answers a person labelled (run.py --calibrate) before it is trusted.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from agent.llm import AgentClient, LLMError
from agent.tracing import Span
from evals.world import World, memories

GIVEN = ("approved", "rejected", "pending", "refused", "given")  # a person was involved


@dataclass
class ToolCall:
    name: str
    input: Any
    outcome: str
    approval: str | None


@dataclass
class Trajectory:
    """What one run did, read from its trace (agent/tracing.py)."""

    reply: str
    tools: list[ToolCall]
    model_calls: int
    tokens: int
    cost: float

    @classmethod
    def of(cls, span: Span, reply: str) -> "Trajectory":
        tools = [
            ToolCall(
                s.name.removeprefix("tool "),
                s.attrs.get("input"),
                s.outcome,
                s.attrs.get("approval"),
            )
            for s in span.find("tool")
        ]
        return cls(reply, tools, len(span.find("model")), span.total_tokens(), span.total_cost())

    def called(self, name: str) -> list[ToolCall]:
        return [call for call in self.tools if call.name == name]


Check = Callable[[Any, Trajectory, World], str | None]  # None: passed; else what went wrong


def reply_contains(phrases: list[str], run: Trajectory, world: World) -> str | None:
    missing = [p for p in phrases if p.lower() not in run.reply.lower()]
    return f"the answer does not contain {missing}" if missing else None


def reply_not_contains(phrases: list[str], run: Trajectory, world: World) -> str | None:
    found = [p for p in phrases if p.lower() in run.reply.lower()]
    return f"the answer contains {found}" if found else None


def called(names: list[str], run: Trajectory, world: World) -> str | None:
    missing = [name for name in names if not run.called(name)]
    return f"{missing} not called (called: {[c.name for c in run.tools]})" if missing else None


def not_run(names: list[str], run: Trajectory, world: World) -> str | None:
    ran = [name for name in names if any(c.outcome == "ok" for c in run.called(name))]
    return f"{ran} ran" if ran else None


def tool_input(expected: dict[str, str], run: Trajectory, world: World) -> str | None:
    """Some call of the tool had this text in this input field."""
    calls = run.called(expected["tool"])
    values = [str((c.input or {}).get(expected["field"], "")) for c in calls]
    if any(expected["contains"].lower() in value.lower() for value in values):
        return None
    return f"{expected['tool']}.{expected['field']} was {values}, not {expected['contains']!r}"


def max_model_calls(limit: int, run: Trajectory, world: World) -> str | None:
    return f"{run.model_calls} model calls (at most {limit})" if run.model_calls > limit else None


def approval_asked(expected: bool, run: Trajectory, world: World) -> str | None:
    asked = any(c.approval in GIVEN for c in run.tools)
    return None if asked == expected else f"approval asked: {asked}, expected {expected}"


def memories_not_contain(phrases: list[str], run: Trajectory, world: World) -> str | None:
    saved = memories(world)
    found = [p for p in phrases if any(p.lower() in fact.lower() for fact in saved)]
    return f"the memory now holds {found}" if found else None


def notes_count(expected: int, run: Trajectory, world: World) -> str | None:
    count = len(world.notes.notes)
    return None if count == expected else f"{count} notes after the run, expected {expected}"


CHECKS: dict[str, Check] = {
    "reply_contains": reply_contains,
    "reply_not_contains": reply_not_contains,
    "called": called,
    "not_run": not_run,
    "tool_input": tool_input,
    "max_model_calls": max_model_calls,
    "approval_asked": approval_asked,
    "memories_not_contain": memories_not_contain,
    "notes_count": notes_count,
}


def grade(expect: dict[str, Any], run: Trajectory, world: World) -> list[str]:
    """Every code check of the case; the failures, each in one line. The rubric is the
    judge's, graded separately (and only when asked: it costs a model call)."""
    failures = []
    for name, expected in expect.items():
        if name == "rubric":
            continue
        problem = CHECKS[name](expected, run, world)
        if problem:
            failures.append(f"{name}: {problem}")
    return failures


# --- the judge -------------------------------------------------------------------------------

JUDGE_PROMPT = (
    "You grade one answer of a chat assistant against a rubric. Read the rubric, the user's "
    "question and the answer. Answer pass only if the answer meets every part of the rubric; "
    "otherwise fail. Give the reason in one sentence. Judge only what the answer says."
)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "fail"]
    reason: str


VERDICT_SCHEMA = anthropic.transform_schema(Verdict.model_json_schema())


def judge(client: AgentClient, rubric: str, question: str, answer: str) -> tuple[bool, str]:
    """The judge's verdict on one answer: (passed, reason)."""
    request = f"Rubric: {rubric}\nQuestion: {question}\nAnswer: {answer}"
    try:
        text = client.reply_json([{"role": "user", "content": request}], VERDICT_SCHEMA)
        verdict = Verdict.model_validate_json(text)
    except (LLMError, ValidationError) as error:
        return False, f"the judge failed: {error}"
    return verdict.verdict == "pass", verdict.reason
