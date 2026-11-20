"""Traces of agent runs: one message as a tree of spans, saved as a JSON file.

A span is one piece of work with a start, an end and an outcome: the message, the router,
the orchestrator, a subagent, one model call, one tool call. Each span knows its children,
so one message reads as a tree: who called whom, how long each took, what it cost, and where
it failed. The logs (chapter 13) say what happened line by line; a trace says how the lines
fit together.

The current span lives in a ContextVar, like the request id: a span opened inside another
becomes its child, and a thread started with copy_context() (chapter 20) adds its spans to
the right parent.

Read a saved trace:  uv run python -m agent.tracing traces/<request id>.json
"""

import json
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent import logs

KINDS = ("input", "cache_read", "cache_write", "output")


@dataclass
class Span:
    name: str
    kind: str  # message, router, team, subagent, model, tool, compaction, eval
    agent: str | None = None  # logs.agent when it started: orchestrator/notes, ...
    started: float = field(default_factory=time.perf_counter)
    ended: float | None = None
    outcome: str = "ok"
    attrs: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=dict)  # this span's own model calls
    cost: float = 0.0  # dollars, this span's own model calls
    children: list["Span"] = field(default_factory=list)

    def add_usage(self, model: str, tokens: tuple[int, int, int, int], cost: float) -> None:
        """Count one model response here (a retry on another model adds a second one)."""
        for kind, value in zip(KINDS, tokens, strict=True):
            self.tokens[kind] = self.tokens.get(kind, 0) + value
        self.cost += cost
        self.attrs["model"] = model

    def walk(self) -> Iterator["Span"]:
        yield self
        for child in list(self.children):
            yield from child.walk()

    def total_tokens(self) -> int:
        return sum(sum(span.tokens.values()) for span in self.walk())

    def total_cost(self) -> float:
        return sum(span.cost for span in self.walk())

    def find(self, kind: str) -> list["Span"]:
        """Every span of this kind in the tree, in the order they started."""
        return sorted((s for s in self.walk() if s.kind == kind), key=lambda s: s.started)


current: ContextVar[Span | None] = ContextVar("span", default=None)
_lock = threading.Lock()  # subagents add children to the same parent from two threads


@contextmanager
def span(name: str, kind: str, **attrs: Any) -> Iterator[Span]:
    """Open a span as a child of the current one (or as a root), and close it on exit. An
    exception marks it "error" and goes on: a trace records failures, it does not hide them."""
    parent = current.get()
    opened = Span(name, kind, logs.agent.get(), attrs=dict(attrs))
    if parent is not None:
        with _lock:
            parent.children.append(opened)
    token = current.set(opened)
    try:
        yield opened
    except BaseException as error:
        if opened.outcome == "ok":  # a span may have said why already ("paused")
            opened.outcome = "error"
        opened.attrs["error"] = type(error).__name__
        raise
    finally:
        opened.ended = time.perf_counter()
        current.reset(token)


def to_dict(span: Span, origin: float | None = None) -> dict[str, Any]:
    """A span and its children as plain JSON data; times in ms from the root's start."""
    origin = span.started if origin is None else origin
    ended = span.ended if span.ended is not None else time.perf_counter()
    data: dict[str, Any] = {
        "name": span.name,
        "kind": span.kind,
        "agent": span.agent,
        "start_ms": round((span.started - origin) * 1000),
        "ms": round((ended - span.started) * 1000),
        "outcome": span.outcome,
        "attrs": span.attrs,
    }
    if span.tokens:
        data["tokens"] = span.tokens
        data["cost_usd"] = round(span.cost, 6)
    data["children"] = [to_dict(child, origin) for child in span.children]
    return data


def save(root: Span, directory: str) -> Path:
    """Write the trace to <directory>/<request id>.json and return the path."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    name = logs.request_id.get() or logs.new_request_id()
    data = to_dict(root)
    data["request_id"] = name
    data["total_tokens"] = root.total_tokens()
    data["total_cost_usd"] = round(root.total_cost(), 6)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), "utf-8")
    return path


def label(data: dict[str, Any]) -> str:
    """One line for one span: name, time, outcome, and what matters for its kind."""
    parts = [data["name"], f"{data['ms']} ms", data["outcome"]]
    attrs = data.get("attrs", {})
    for key in ("route", "stop", "status", "approval", "input", "error", "fallback"):
        if key in attrs:
            value = attrs[key]
            text = json.dumps(value, ensure_ascii=False) if key == "input" else str(value)
            parts.append(f"{key}={text}")
    tokens = data.get("tokens")
    if tokens:
        parts.append(f"tokens={sum(tokens.values())}")
        parts.append(f"${data['cost_usd']:.4f}")
    return "  ".join(parts)


def render(data: dict[str, Any], prefix: str = "", last: bool = True, top: bool = True) -> str:
    """The tree, one span per line, children indented under their parent."""
    lines = [label(data) if top else f"{prefix}{'`- ' if last else '|- '}{label(data)}"]
    inner = "" if top else prefix + ("   " if last else "|  ")
    children = data.get("children", [])
    for number, child in enumerate(children):
        lines.append(render(child, inner, number == len(children) - 1, False))
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m agent.tracing <trace file>")
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(
        f"request {data.get('request_id')}: {data.get('total_tokens')} tokens, "
        f"${data.get('total_cost_usd', 0):.4f}"
    )
    print(render(data))


if __name__ == "__main__":
    main()
