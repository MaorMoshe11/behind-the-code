"""The agent loop, written by hand.

Call the model with the tools it may use (a Toolbox, from the registry in agent/tools.py).
If it asks for tools, run them here, add its request and our results to the conversation,
and call it again. Nothing here knows any particular tool. Stop when it answers
without asking for a tool, or after max_steps calls, whichever comes first.

The same loop runs every agent: the chat, the orchestrator and each subagent (chapter 20).
"""

import logging
from dataclasses import dataclass
from typing import Any

from anthropic.types import MessageParam

from agent import logs
from agent.llm import AgentClient, count, text_of
from agent.metrics import AGENT_RUNS, AGENT_STEPS, AGENT_TOKENS
from agent.tools import Toolbox

log = logging.getLogger(__name__)
KINDS = ("input", "cache_read", "cache_write", "output")
GAVE_UP = "I could not finish this in {steps} steps, so I stopped. Try a simpler question."


@dataclass
class AgentRun:
    reply: str  # the text for the user
    stop: str  # why the loop ended: end_turn, max_steps, refusal, max_tokens, ...
    steps: int  # model calls made
    tool_calls: int  # tools run
    messages: list[MessageParam]  # the whole run: question, tool requests, results, answer


def run_agent(
    client: AgentClient,
    messages: list[MessageParam],
    toolbox: Toolbox,
    max_steps: int,
    schema: dict[str, Any] | None = None,
) -> AgentRun:
    """Run the loop on a copy of `messages` (the conversation so far, ending with the question).

    With a `schema`, the final answer must be JSON that matches it (structured output): how a
    subagent hands back its report.
    """
    messages = list(messages)  # our own list: the caller's is not changed
    params = toolbox.params()
    tool_calls = 0
    who = logs.agent.get() or "chat"  # whose tokens these are, for the metrics
    for step in range(1, max_steps + 1):
        if schema is None:
            response = client.create(messages, params)
        else:
            response = client.create(messages, params, schema)
        usage = response.usage
        cache_read = count(usage.cache_read_input_tokens)
        cache_write = count(usage.cache_creation_input_tokens)
        log.info(
            "agent step %d: %s",
            step,
            response.stop_reason,
            extra={
                "step": step,
                "stop_reason": response.stop_reason,
                # The prompt is input + cache_read + cache_write: input is only the part
                # the cache did not touch (chapter 19).
                "input_tokens": usage.input_tokens,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "output_tokens": usage.output_tokens,
                "api_request_id": getattr(response, "_request_id", None),  # None in mock mode
            },
        )
        spent = (usage.input_tokens, cache_read, cache_write, usage.output_tokens)
        for kind, value in zip(KINDS, spent, strict=True):
            AGENT_TOKENS.labels(who, kind).inc(value)
        # Its whole answer goes back next time, unchanged: text, tool requests, thinking.
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":  # it answered (or refused, or ran out of room)
            stop = response.stop_reason or "unknown"
            return finish(AgentRun(text_of(response), stop, step, tool_calls, messages))
        calls = [block for block in response.content if block.type == "tool_use"]
        # One request may hold several calls. Every result of this step goes in ONE user
        # message, each one tied to its request by id, in the order of the requests.
        messages.append({"role": "user", "content": toolbox.results(calls)})
        tool_calls += len(calls)
    log.warning("agent stopped after %d steps", max_steps, extra={"tool_calls": tool_calls})
    reply = GAVE_UP.format(steps=max_steps)
    return finish(AgentRun(reply, "max_steps", max_steps, tool_calls, messages))


def finish(run: AgentRun) -> AgentRun:
    """Count the run, by how it ended."""
    AGENT_RUNS.labels(run.stop).inc()
    AGENT_STEPS.observe(run.steps)
    return run
