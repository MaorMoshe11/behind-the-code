"""The agent loop, written by hand.

Call the model with the tools it may use. If it asks for tools, run them here, add its
request and our results to the conversation, and call it again. Stop when it answers
without asking for a tool, or after max_steps calls, whichever comes first.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from anthropic.types import MessageParam, ToolResultBlockParam, ToolUseBlock

from agent.llm import AgentClient, text_of
from agent.metrics import AGENT_RUNS, AGENT_STEPS, AGENT_TOOL_CALLS
from agent.tools import Tool, ToolError

log = logging.getLogger(__name__)
GAVE_UP = "I could not finish this in {steps} steps, so I stopped. Try a simpler question."


@dataclass
class AgentRun:
    reply: str  # the text for the user
    stop: str  # why the loop ended: end_turn, max_steps, refusal, max_tokens, ...
    steps: int  # model calls made
    tool_calls: int  # tools run
    messages: list[MessageParam]  # the whole run: question, tool requests, results, answer


def run_tool(tools: dict[str, Tool], call: ToolUseBlock) -> ToolResultBlockParam:
    """Run one tool call. Whatever happens, the model gets a result: never an exception."""
    tool = tools.get(call.name)
    try:
        if tool is None:
            raise ToolError(f"There is no tool named {call.name!r}.")
        content, is_error = tool.run(call.input), False
    except ToolError as error:  # an expected failure: the message is written for the model
        content, is_error = str(error), True
    except Exception:  # a bug in our tool: the details go to our log, not to the model
        log.exception("tool %s crashed", call.name)
        content, is_error = "The tool failed unexpectedly.", True
    outcome = "error" if is_error else "ok"
    AGENT_TOOL_CALLS.labels(call.name if tool else "unknown", outcome).inc()
    level = logging.WARNING if is_error else logging.INFO
    log.log(level, "tool %s: %s", call.name, outcome, extra={"tool": call.name, "outcome": outcome})
    return {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error}


def run_agent(
    client: AgentClient, messages: list[MessageParam], tools: Sequence[Tool], max_steps: int
) -> AgentRun:
    """Run the loop on a copy of `messages` (the conversation so far, ending with the question)."""
    messages = list(messages)  # our own list: the caller's is not changed
    by_name = {tool.name: tool for tool in tools}
    params = [tool.param() for tool in tools]
    tool_calls = 0
    for step in range(1, max_steps + 1):
        response = client.create(messages, params)
        log.info(
            "agent step %d: %s",
            step,
            response.stop_reason,
            extra={
                "step": step,
                "stop_reason": response.stop_reason,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "api_request_id": getattr(response, "_request_id", None),  # None in mock mode
            },
        )
        # Its whole answer goes back next time, unchanged: text, tool requests, thinking.
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":  # it answered (or refused, or ran out of room)
            stop = response.stop_reason or "unknown"
            return finish(AgentRun(text_of(response), stop, step, tool_calls, messages))
        calls = [block for block in response.content if block.type == "tool_use"]
        # Every result of this step in ONE user message, each one tied to its request by id.
        messages.append({"role": "user", "content": [run_tool(by_name, call) for call in calls]})
        tool_calls += len(calls)
    log.warning("agent stopped after %d steps", max_steps, extra={"tool_calls": tool_calls})
    reply = GAVE_UP.format(steps=max_steps)
    return finish(AgentRun(reply, "max_steps", max_steps, tool_calls, messages))


def finish(run: AgentRun) -> AgentRun:
    """Count the run, by how it ended."""
    AGENT_RUNS.labels(run.stop).inc()
    AGENT_STEPS.observe(run.steps)
    return run
