"""The context: what the model sees on one call, assembled within a budget.

Every call sends the system prompt, the tool definitions, the conversation so far and the
new question. The window has a size, and every token in it costs money and time, so the
program decides what goes in: build_context() takes the stored history and returns the
messages to send, with a report of where the tokens go (a Budget).

The stored history (the database) is the truth. The context is a view of it.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from anthropic.types import MessageParam, ToolParam

# The first line of the summary message that stands in for older turns (agent/compaction.py).
SUMMARY_HEADER = "[Summary of the earlier conversation, written by the program]"
# A tool result kept in the history is cut to this many characters: the run that called the
# tool saw all of it; later turns get the start, and can call the tool again.
STORED_RESULT_CHARS = 1000


def plain(value: Any) -> Any:
    """SDK objects (the model's blocks) as plain JSON data, the way they go over the wire."""
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def fingerprint(system: str, tools: list[ToolParam]) -> str:
    """A short version of the prompt: 8 hex characters that change whenever the system prompt
    or any tool's name, description or schema changes. Logged with every answer and saved with
    every eval run, so a change in behaviour can be matched to a change in the prompt."""
    data = json.dumps([system, plain(tools)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()[:8]


def estimate(value: object) -> int:
    """About one token per four characters. Cheap and offline, so it can run on every call.

    Only an estimate: the API's count_tokens is exact, and every response reports the real
    count in `usage`. Text in Hebrew, code or JSON has more tokens per character than English.
    """
    text = value if isinstance(value, str) else json.dumps(plain(value), sort_keys=True)
    return len(text) // 4 + 1


def is_question(message: MessageParam) -> bool:
    """A message the user typed: role user, plain text (tool results are lists of blocks)."""
    content = message["content"]
    return (
        message["role"] == "user"
        and isinstance(content, str)
        and not content.startswith(SUMMARY_HEADER)
    )


def split_turns(history: list[MessageParam]) -> list[list[MessageParam]]:
    """Cut the history into turns. A turn starts with a question and holds everything up to
    the next one: the answer, and any tool requests and results in between.

    Trimming works on whole turns only, so a tool request is never sent without its result
    (the API refuses that with a 400) and a turn never starts with an answer.
    """
    turns: list[list[MessageParam]] = []
    for message in history:
        if is_question(message) or not turns:
            turns.append([])
        turns[-1].append(message)
    return turns


def summary_message(summary: str) -> MessageParam:
    return {"role": "user", "content": f"{SUMMARY_HEADER}\n{summary}"}


def shrink_result(message: MessageParam) -> MessageParam:
    """The message as it is kept in the history: long tool results cut, with a note saying so."""
    content = message["content"]
    if isinstance(content, str):
        return message
    blocks = []
    for block in plain(content):
        text = block.get("content")
        if block.get("type") == "tool_result" and isinstance(text, str):
            if len(text) > STORED_RESULT_CHARS:
                cut = len(text) - STORED_RESULT_CHARS
                text = f"{text[:STORED_RESULT_CHARS]}\n[... {cut} more characters were cut when "
                text += "this result was stored. Call the tool again for all of it.]"
                block = {**block, "content": text}
        blocks.append(block)
    if message["role"] == "user":
        return {"role": "user", "content": blocks}
    return {"role": "assistant", "content": blocks}


@dataclass(frozen=True)
class Budget:
    """Where the tokens of one call go (estimated), and what did not fit."""

    limit: int
    system: int
    tools: int
    summary: int
    history: int
    question: int
    kept: int  # turns sent
    dropped: int  # turns left out: they did not fit

    @property
    def total(self) -> int:
        return self.system + self.tools + self.summary + self.history + self.question

    def report(self) -> str:
        rows = [
            ("system", self.system, ""),
            ("tools", self.tools, ""),
            ("summary", self.summary, ""),
            ("history", self.history, f"turns: {self.kept} sent, {self.dropped} left out"),
            ("question", self.question, ""),
        ]
        lines = [f"  {name:<9}{tokens:>6}  {note}".rstrip() for name, tokens, note in rows]
        lines.append(f"  {'total':<9}{self.total:>6}  of {self.limit}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Context:
    messages: list[MessageParam]  # what to send, in order
    budget: Budget


def build_context(
    system: str,
    tools: list[ToolParam],
    history: list[MessageParam],
    question: MessageParam | None,
    limit: int,
    max_turns: int,
    summary: str | None = None,
) -> Context:
    """The messages for one call: the summary (if any), the newest whole turns that fit in
    `limit` tokens and `max_turns` turns, and the question. Older turns are left out."""
    fixed = estimate(system) + estimate(tools)
    summary_tokens = estimate(summary_message(summary)) if summary else 0
    question_tokens = estimate(question) if question else 0
    room = limit - fixed - summary_tokens - question_tokens
    turns = split_turns(history)
    kept: list[list[MessageParam]] = []
    used = 0
    for turn in reversed(turns):  # newest first: the end of a conversation matters most
        size = sum(estimate(message) for message in turn)
        if len(kept) == max_turns or used + size > room:
            break
        kept.insert(0, turn)
        used += size
    messages = [summary_message(summary)] if summary else []
    messages += [message for turn in kept for message in turn]
    if question:
        messages.append(question)
    budget = Budget(
        limit=limit,
        system=estimate(system),
        tools=estimate(tools),
        summary=summary_tokens,
        history=used,
        question=question_tokens,
        kept=len(kept),
        dropped=len(turns) - len(kept),
    )
    return Context(messages, budget)
