"""Clients that turn a conversation into a reply.

ClaudeClient talks to the real Claude API. MockClient returns fake replies,
costs nothing, and is the one the tests use.

reply() is one call: messages in, text out. create() is one step of the agent loop
(agent/loop.py): the model may answer, or ask for one or more of the tools it was offered.
reply_json() is one call whose answer must be JSON that matches a schema (structured
output); agent/titles.py checks it with Pydantic.

Every call asks the API to cache the prompt (prompt caching): the next call that starts
with the same bytes pays far less for that part. The usage of each response says how much
was read from the cache and how much was written to it.
"""

import hashlib
import json
import logging
import re
import time
from typing import Any, Protocol

import anthropic
from anthropic.types import (
    CacheControlEphemeralParam,
    Message,
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
    ToolParam,
    Usage,
)

from agent.config import SYSTEM_PROMPT
from agent.context import estimate, is_question, plain
from agent.metrics import LLM_ERRORS, LLM_TOKENS

log = logging.getLogger(__name__)
REFUSED = "(The model declined to answer this request.)"


class LLMError(Exception):
    """The model could not answer. `fatal` means that trying again will not help."""

    def __init__(self, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class ChatClient(Protocol):
    """Anything that can answer a conversation."""

    def reply(self, messages: list[MessageParam]) -> str: ...


class AgentClient(ChatClient, Protocol):
    """A client the agent loop can drive: one model call, with tools, the whole response back."""

    def create(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam],
        schema: dict[str, Any] | None = None,
    ) -> Message:
        """One step. With a schema, the final answer must be JSON that matches it."""
        ...

    def reply_json(self, messages: list[MessageParam], schema: dict[str, Any]) -> str: ...

    def count_tokens(self, messages: list[MessageParam], tools: list[ToolParam]) -> int: ...


def count(value: object) -> int:
    """A token count from `usage`: the cache fields are None when the API did not fill them."""
    return value if isinstance(value, int) else 0


def record_usage(usage: Any) -> tuple[int, int, int, int]:
    """Count one response's tokens into llm_tokens_total, by kind, and return them:
    (input, cache_read, cache_write, output). `input` is only the part that was neither
    read from nor written to the cache: the whole prompt is the sum of the first three."""
    tokens = (
        count(usage.input_tokens),
        count(usage.cache_read_input_tokens),
        count(usage.cache_creation_input_tokens),
        count(usage.output_tokens),
    )
    for kind, value in zip(("input", "cache_read", "cache_write", "output"), tokens, strict=True):
        LLM_TOKENS.labels(kind).inc(value)
    return tokens


def text_of(response: Message) -> str:
    """The text blocks of a response, joined. Other blocks (tool_use, thinking) are skipped."""
    if response.stop_reason == "refusal":
        return REFUSED
    return "".join(block.text for block in response.content if block.type == "text")


CACHE: CacheControlEphemeralParam = {"type": "ephemeral"}  # 5 minutes, renewed by every hit


class ClaudeClient:
    """Sends the whole conversation to Claude and returns the reply text."""

    def __init__(
        self, model: str, system_prompt: str, sdk: anthropic.Anthropic | None = None
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        # Tests pass a fake SDK client here, so they never touch the network.
        self.sdk = sdk or anthropic.Anthropic()

    def _create(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam] | anthropic.Omit,
        output_config: OutputConfigParam | anthropic.Omit = anthropic.omit,
    ) -> Message:
        """One request to the Messages API, with our error handling and our metrics."""
        try:
            response = self.sdk.messages.create(
                model=self.model,
                max_tokens=16000,
                system=self.system(),
                messages=messages,
                tools=tools,
                output_config=output_config,
                # Automatic caching: a breakpoint on the last block, moved forward every
                # call, so next time the conversation so far is read from the cache.
                cache_control=CACHE,
            )
        # Most specific first: each reason gets its own message and its own metric label,
        # so a graph can tell "our key is wrong" from "the network is down".
        except anthropic.AuthenticationError as error:
            LLM_ERRORS.labels("auth").inc()
            raise LLMError(
                "The API rejected your key. Check ANTHROPIC_API_KEY.", fatal=True
            ) from error
        except anthropic.RateLimitError as error:
            LLM_ERRORS.labels("rate_limited").inc()
            raise LLMError("Too many requests to the API. Wait a minute and try again.") from error
        except anthropic.APIStatusError as error:
            LLM_ERRORS.labels("status").inc()
            raise LLMError(f"The API returned an error ({error.status_code}).") from error
        except anthropic.APITimeoutError as error:  # a kind of APIConnectionError: first
            LLM_ERRORS.labels("timeout").inc()
            raise LLMError("The API did not answer in time. Try again.") from error
        except anthropic.APIConnectionError as error:
            LLM_ERRORS.labels("connection").inc()
            raise LLMError("Could not reach the API. Check your internet connection.") from error

        uncached, read, written, output = record_usage(response.usage)
        log.info(
            "reply from %s: %d input tokens, %d output tokens, %d read from cache, %d written",
            self.model,
            uncached,
            output,
            read,
            written,
            # Anthropic's own id for this call: what their support asks for.
            extra={"api_request_id": response._request_id},
        )
        return response

    def system(self) -> list[TextBlockParam]:
        """The system prompt, with its own cache breakpoint. Tools and system come first in
        every request, so this caches both, whatever happens later in the messages."""
        return [{"type": "text", "text": self.system_prompt, "cache_control": CACHE}]

    def count_tokens(self, messages: list[MessageParam], tools: list[ToolParam]) -> int:
        """The exact input tokens of a request, counted by the API (one more request)."""
        try:
            counted = self.sdk.messages.count_tokens(
                model=self.model, system=self.system(), messages=messages, tools=tools
            )
        except anthropic.APIError as error:
            raise LLMError("Could not count the tokens.") from error
        return counted.input_tokens

    def reply(self, messages: list[MessageParam]) -> str:
        return text_of(self._create(messages, anthropic.omit))  # no tools: one plain call

    def create(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam],
        schema: dict[str, Any] | None = None,
    ) -> Message:
        if schema is None:
            return self._create(messages, tools)
        # Tools and a JSON answer in one request: the model may still call tools, and its
        # final text must match the schema (structured outputs; a subagent's report).
        output: OutputConfigParam = {"format": {"type": "json_schema", "schema": schema}}
        return self._create(messages, tools, output)

    def reply_json(self, messages: list[MessageParam], schema: dict[str, Any]) -> str:
        """The answer as JSON text that matches `schema` (the API's structured outputs)."""
        output: OutputConfigParam = {"format": {"type": "json_schema", "schema": schema}}
        response = self._create(messages, anthropic.omit, output)
        if response.stop_reason in ("refusal", "max_tokens"):  # then it may not match
            raise LLMError(f"The model did not finish its JSON answer ({response.stop_reason}).")
        return text_of(response)


def mock_tokens(text: str) -> int:
    """A made-up but steady token count: about one token per four characters."""
    return len(text) // 4 + 1


# How a test or a reader makes the mock ask for tools (see MockClient.create):
CALL = re.compile(r"\[mock:call (\w+) (\{.*?\})\]")  # [mock:call list_notes {"search": 42}]
LOOP = "[mock:loop]"  # ask for the same tools again after every result: a loop that never ends
NOTES = re.compile(r"\bnotes\b", re.IGNORECASE)  # "what is in my notes?" -> list_notes
ABOUT = re.compile(r"\babout ([^?.!\n]+)", re.IGNORECASE)  # "... about milk?" -> search "milk"
REMEMBER = re.compile(r"\bremember that ([^?.!\n]+)", re.IGNORECASE)  # -> add_note, each one
TIME = re.compile(r"\bwhat (?:time|day|date)\b", re.IGNORECASE)  # -> current_time
FORGET = re.compile(r"\bforget note \[?([0-9a-f]{8})\]?", re.IGNORECASE)  # -> delete_note
UNREMEMBER = re.compile(r"\bforget memory \[?([0-9a-f]{8})\]?", re.IGNORECASE)  # forget_memory
# How a test or a reader makes the mock answer reply_json() with exactly this text:
JSON = re.compile(r"\[mock:json (\{.*?\})\]")  # [mock:json {"title": ""}] -> '{"title": ""}'
RETRY_MARK = "Your previous answer was rejected"  # agent/titles.py starts each retry with it
COMPACT_MARK = "Summarise the conversation"  # agent/compaction.py starts its request with it
KEEP = re.compile(r"\bkeep in mind that ([^?.!\n]+)", re.IGNORECASE)  # -> remember
RECALL = re.compile(r"\bwhat do you (?:know|remember) about me\b", re.IGNORECASE)  # -> recall
EARLIER = re.compile(  # "Did we talk about the cake?" -> search_conversations "the cake"
    r"\b(?:did|have) we (?:ever )?(?:talk|talked|speak|spoken|discuss|discussed) about "
    r"([^?.!\n]+)",
    re.IGNORECASE,
)
# The team (chapter 20). The router asks reply_json for a "route"; the mock sends a message
# to the team when it asks to go over, review or collect many things:
TEAM = re.compile(r"\b(?:go (?:over|through)|review|all my|everything)\b", re.IGNORECASE)
# The orchestrator delegates to the memory specialist when these appear (to notes on "notes"):
EARLIER_WORK = re.compile(
    r"\b(?:conversations?|talked|discussed|decided|memor(?:y|ies)|remember)\b", re.IGNORECASE
)
ARTICLE = re.compile(r"^(?:the|my|our|a|an) ", re.IGNORECASE)
REPORT = re.compile(r"\w+ specialist: ")  # the first words of a subagent's result
GAPS = ("- ", "not found:", "problem:", "unchecked")  # the lines an orchestrator passes on
INVENT = "[mock:invent]"  # a subagent adds a finding no tool returned: to test verification
# The smallest prompt the API caches for claude-opus-5-5. Shorter prompts are simply not
# cached: no error, cache_creation_input_tokens stays 0.
MIN_CACHE = 512

Call = tuple[str, dict[str, Any]]


def wanted_calls(question: str, offered: set[str]) -> list[Call]:
    """The tool calls the mock 'decides' to make for this question; [] for a plain answer.

    Several calls come back in one response, as a real model may do (parallel tool use).
    """
    scripted = CALL.findall(question)
    if scripted:  # exactly what the message says, offered or not: for testing bad calls
        return [(name, json.loads(tool_input)) for name, tool_input in scripted]
    calls: list[Call] = []
    if "add_note" in offered:
        calls += [("add_note", {"text": text.strip()}) for text in REMEMBER.findall(question)]
    if "delete_note" in offered:
        calls += [("delete_note", {"note": ref.lower()}) for ref in FORGET.findall(question)]
    if "remember" in offered:
        calls += [("remember", {"text": text.strip()}) for text in KEEP.findall(question)]
    if "forget_memory" in offered:
        calls += [("forget_memory", {"memory": r.lower()}) for r in UNREMEMBER.findall(question)]
    if "recall" in offered and RECALL.search(question):
        calls.append(("recall", {}))
    if "search_conversations" in offered:
        calls += [("search_conversations", {"query": q.strip()}) for q in EARLIER.findall(question)]
    if not calls and "list_notes" in offered and NOTES.search(question):
        about = ABOUT.search(question)
        calls.append(("list_notes", {"search": about.group(1).strip()} if about else {}))
    if not calls and "current_time" in offered and TIME.search(question):
        calls.append(("current_time", {}))
    if "delegate" in offered:  # the orchestrator plans: one call per specialist
        calls += plan(question)
    return calls


def topic_of(text: str) -> str:
    """The first word after "about", past an article: "about the party and ..." -> "party"."""
    about = ABOUT.search(text)
    words = ARTICLE.sub("", about.group(1).strip()).split() if about else []
    return words[0].strip(",;:") if words else ""


def plan(question: str) -> list[Call]:
    """The mock orchestrator's plan: a brief for the notes specialist, the memory specialist,
    or both (when the question names neither), all in one response, so they can run at once."""
    wanted = [
        name
        for name, pattern in (("notes", NOTES), ("memory", EARLIER_WORK))
        if pattern.search(question)
    ] or ["notes", "memory"]
    topic = topic_of(question)
    goals = {
        "notes": f"Find the notes the user saved about {topic}." if topic else "List the notes.",
        "memory": (
            f"Find what the user said about {topic} in earlier conversations, and what is "
            "remembered about them."
            if topic
            else "Find what is remembered about the user."
        ),
    }
    return [
        (
            "delegate",
            {
                "specialist": name,
                "goal": goals[name],
                "context": f'The user asked in the chat: "{question}"',
                "done_when": "Every match is listed with its source, or you are sure of none.",
            },
        )
        for name in wanted
    ]


def worker_calls(brief: str, offered: set[str]) -> list[Call]:
    """A mock subagent uses each of its reading tools once, on the brief's topic."""
    scripted = CALL.findall(brief)
    if scripted:
        return [(name, json.loads(tool_input)) for name, tool_input in scripted]
    topic = topic_of(brief)
    calls: list[Call] = []
    if "list_notes" in offered:
        calls.append(("list_notes", {"search": topic} if topic else {}))
    if "search_conversations" in offered and topic:
        calls.append(("search_conversations", {"query": topic}))
    if "recall" in offered:
        calls.append(("recall", {}))
    return calls


def mock_report(brief: str, results: Any) -> str:
    """A mock subagent's report, as JSON: each "- " line of a result that mentions the brief's
    topic is a finding with its source (the rest is read, and left out: what a specialist is
    for); an empty result is something not found; a failed tool is a problem."""
    topic = topic_of(brief).lower()
    findings: list[dict[str, str]] = []
    not_found: list[str] = []
    problems: list[str] = []
    for block in results if isinstance(results, list) else []:
        content = str(block.get("content", ""))
        if block.get("is_error"):
            problems.append(content)
            continue
        lines = [line[2:] for line in content.splitlines() if line.startswith("- ")]
        if not lines:
            not_found.append(content)
        for line in [line for line in lines if topic in line.lower()]:
            if line.startswith("["):  # "[3f2a91c0] buy oat milk": a note or a memory, by ref
                source, _, fact = line.partition("] ")
                findings.append({"fact": fact, "source": source + "]"})
            else:  # '2026-11-19, "Party plans", user: ...': a message in a conversation
                source, _, fact = line.partition('", ')
                findings.append({"fact": fact, "source": source + '"'})
    if INVENT in brief:
        findings.append({"fact": "The party was moved to Friday.", "source": "[0badc0de]"})
    report = {"findings": findings, "not_found": not_found, "problems": problems}
    return json.dumps(report, ensure_ascii=False)


def mock_value(schema: dict[str, Any], name: str) -> Any:
    """A made-up value of the right type for one property of a JSON schema."""
    if "enum" in schema:
        return schema["enum"][-1]
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties", {})
        return {key: mock_value(value, key) for key, value in properties.items()}
    made_up: dict[str, Any] = {"string": f"mock {name}", "integer": 1, "boolean": False}
    return made_up.get(str(kind), [])


class MockClient:
    """Returns a predictable fake reply. Free, offline, the same every time.

    It also plays the API's prompt cache, so caching can be seen offline: a request whose
    start is byte for byte the start of an earlier request reads that part "from the cache".
    The numbers are the mock's (about a token per four characters), not the API's.
    """

    def __init__(self, system_prompt: str = SYSTEM_PROMPT, delay: float = 0.0) -> None:
        self.system_prompt = system_prompt
        self.delay = delay  # seconds to wait per call (CHAT_MOCK_DELAY): a model takes time
        self.cache: set[str] = set()  # fingerprints of the prompts written to the cache

    def usage(self, messages: list[MessageParam], tools: list[ToolParam]) -> dict[str, int]:
        """What the API would bill: tools, system, then each message, as one long prefix.

        Like a request with a breakpoint on the system prompt and automatic caching: the
        longest start already in the cache is read, and the whole prompt is written if it is
        at least MIN_CACHE tokens. Nothing expires here; the real cache forgets after 5
        minutes without a hit.
        """
        parts: list[object] = [tools, self.system_prompt, *messages]
        fingerprint, total, read, marks = "", 0, 0, []
        for part in parts:
            data = fingerprint + json.dumps(plain(part), sort_keys=True)
            fingerprint = hashlib.sha256(data.encode()).hexdigest()
            total += estimate(part)
            if fingerprint in self.cache:
                read = total  # this much of the prompt is the start of an earlier one
            marks.append((fingerprint, total))
        written = 0
        if total >= MIN_CACHE:
            # Both breakpoints: after the system prompt, and at the end of the prompt.
            self.cache.update(mark for mark, size in (marks[1], marks[-1]) if size >= MIN_CACHE)
            written = total - read
        return {
            "input_tokens": total - read - written,
            "cache_read_input_tokens": read,
            "cache_creation_input_tokens": written,
        }

    def count_tokens(self, messages: list[MessageParam], tools: list[ToolParam]) -> int:
        """The mock counts the way agent/context.py estimates: the two numbers agree."""
        return estimate(tools) + estimate(self.system_prompt) + sum(map(estimate, messages))

    def reply(self, messages: list[MessageParam]) -> str:
        time.sleep(self.delay)
        last_message = str(messages[-1]["content"])
        if last_message.startswith(COMPACT_MARK):
            reply = self.summary(last_message)
        else:
            turn = (len(messages) + 1) // 2
            reply = f"[mock reply, turn {turn}] You said: {last_message}"
        # Report usage like the real client does, so the token metrics work offline too.
        usage = self.usage(messages, [])
        output = mock_tokens(reply)
        sent, read, written, _ = record_usage(
            Usage.model_validate({**usage, "output_tokens": output})
        )
        log.debug("mock reply: %d input tokens, %d output tokens", sent + read + written, output)
        return reply

    @staticmethod
    def summary(request: str) -> str:
        """A scripted summary: what the user said, each message cut to 80 characters."""
        said = [
            line[len("User: ") :][:80] for line in request.splitlines() if line.startswith("User: ")
        ]
        before = [line for line in request.splitlines() if line.startswith("Summary so far: ")]
        if before:  # a summary of a summary: the new turns are added to the old ones
            return " | ".join([before[0][len("Summary so far: ") :], *said])
        return "[mock summary] The user said: " + " | ".join(said)

    def create(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam],
        schema: dict[str, Any] | None = None,
    ) -> Message:
        """One scripted agent step, in the same shape as a real response.

        A new question (the last message is the user's text) gets one tool_use block for each
        call wanted_calls() finds, and a plain answer when there is none. Tool results (the
        last message holds tool_result blocks) get an answer that quotes them; with
        [mock:loop] in the question, the same tool calls again, forever.

        With a schema, this is a subagent (chapter 20): it calls its reading tools on the
        brief's topic (worker_calls), and its answer is a JSON report (mock_report).
        """
        time.sleep(self.delay)
        # The question is the user's last text message; the steps of this run come after it.
        # (Earlier turns may hold tool steps too, now that they are stored.)
        questions = [i for i, m in enumerate(messages) if is_question(m)]
        at = questions[-1]
        question, turn = str(messages[at]["content"]), len(questions)
        step = (len(messages) - 1 - at) // 2 + 1
        offered = {tool["name"] for tool in tools}
        worker = schema is not None  # a subagent: it reports in JSON (chapter 20)
        calls = worker_calls(question, offered) if worker else wanted_calls(question, offered)
        last = messages[-1]["content"]
        content: list[dict[str, Any]]
        if calls and (isinstance(last, str) or LOOP in question):
            content = [
                {"type": "tool_use", "id": f"toolu_mock_{step}_{n}", "name": name, "input": args}
                for n, (name, args) in enumerate(calls, start=1)
            ]
            stop_reason = "tool_use"
        elif worker:
            content = [{"type": "text", "text": mock_report(question, last)}]
            stop_reason = "end_turn"
        else:
            content = [{"type": "text", "text": self.answer(question, last, turn)}]
            stop_reason = "end_turn"
        usage = self.usage(messages, tools)
        message = Message.model_validate(
            {
                "id": f"msg_mock_{step}",
                "type": "message",
                "role": "assistant",
                "model": "mock",
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                # Everything is sent again at every step, so the prompt grows with each step;
                # how much of it the cache serves is in the cache_* fields.
                "usage": {**usage, "output_tokens": mock_tokens(str(content))},
            }
        )
        record_usage(message.usage)
        return message

    def reply_json(self, messages: list[MessageParam], schema: dict[str, Any]) -> str:
        """Scripted JSON. The k-th attempt answers with the k-th distinct [mock:json ...] in the
        messages; when there is none left, made-up values that match the schema."""
        time.sleep(self.delay)
        text = " ".join(str(message["content"]) for message in messages)
        scripted: list[str] = list(dict.fromkeys(JSON.findall(text)))  # each once, in order
        attempt = text.count(RETRY_MARK)  # 0 on the first try, 1 on the retry, ...
        if attempt < len(scripted):
            answer = scripted[attempt]
        elif "route" in schema.get("properties", {}):  # the router (agent/router.py)
            route = "team" if TEAM.search(text) else "chat"
            answer = json.dumps({"route": route, "reason": f"mock: {route}"})
        else:
            answer = json.dumps(mock_value(schema, "answer"))
        LLM_TOKENS.labels("input").inc(mock_tokens(text + str(schema)))
        LLM_TOKENS.labels("output").inc(mock_tokens(answer))
        return answer

    @staticmethod
    def answer(question: str, last: Any, turn: int) -> str:
        """The final text: an echo of the question, or what the tool results said."""
        if isinstance(last, str):
            return f"[mock reply, turn {turn}] You said: {question}"
        if all(REPORT.match(str(block["content"])) for block in last):
            return MockClient.combine(last, turn)
        parts = []
        for block in last:  # the tool_result blocks the loop sent back
            if block.get("is_error"):
                parts.append(f"I tried, but the tool failed: {block['content']}")
            else:
                parts.append(f"I looked it up. The tool said:\n{block['content']}")
        return f"[mock reply, turn {turn}] " + "\n".join(parts)

    @staticmethod
    def combine(reports: Any, turn: int) -> str:
        """The mock orchestrator's answer: each specialist's findings and gaps, under its name,
        without the numbers. A real one writes prose; the shape is the same."""
        lines = [f"[mock reply, turn {turn}] What the specialists found:"]
        for block in reports:
            content = str(block["content"]).splitlines()
            lines.append(content[0].split(" specialist")[0] + ":")  # "notes:"
            if block.get("is_error"):  # a run that did not end well: say how
                lines.append(f"- ({content[0]})")
            lines += [line for line in content if line.startswith(GAPS)]
        return "\n".join(lines)
