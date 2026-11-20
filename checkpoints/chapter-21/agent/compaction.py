"""Compaction: older turns become a short summary that stands in for them in the context.

The turns stay in the database (they are the truth); only the context sees the summary.
What a summary loses: exact wording, details nobody thought would matter, and the tool
requests and results (only the questions and answers are summarised).
"""

from anthropic.types import MessageParam

from agent.context import is_question
from agent.llm import COMPACT_MARK, ChatClient

KEEP_TURNS = 2  # the newest turns stay as they are; everything older is summarised
PROMPT = (
    f"{COMPACT_MARK} below, for yourself, to continue it later without the full text. "
    "Keep what the user told you about themselves (names, preferences, constraints such as "
    "allergies), decisions made, open questions and tasks, and exact numbers, dates and "
    "names. Drop small talk. At most 200 words, plain text.\n\n"
)


def transcript(summary: str | None, turns: list[list[MessageParam]]) -> str:
    """The questions and answers as plain text; tool steps are left out."""
    lines = [f"Summary so far: {summary}"] if summary else []
    for turn in turns:
        for message in turn:
            content = message["content"]
            if isinstance(content, str):
                who = "User" if is_question(message) else "Assistant"
                lines.append(f"{who}: {content}")
    return "\n".join(lines)


def summarize(client: ChatClient, summary: str | None, turns: list[list[MessageParam]]) -> str:
    """One model call: the previous summary and the older turns, in, a new summary out."""
    request: list[MessageParam] = [{"role": "user", "content": PROMPT + transcript(summary, turns)}]
    return client.reply(request).strip()
