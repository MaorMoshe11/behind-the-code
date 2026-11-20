"""Clients that turn a conversation into a reply.

ClaudeClient talks to the real Claude API. MockClient returns fake replies,
costs nothing, and is the one the tests use.

reply() is one call: messages in, text out. create() is one step of the agent loop
(agent/loop.py): the model may answer, or ask for one or more of the tools it was offered.
reply_json() is one call whose answer must be JSON that matches a schema (structured
output); agent/titles.py checks it with Pydantic.
"""

import json
import logging
import re
from typing import Any, Protocol

import anthropic
from anthropic.types import Message, MessageParam, OutputConfigParam, ToolParam

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

    def create(self, messages: list[MessageParam], tools: list[ToolParam]) -> Message: ...

    def reply_json(self, messages: list[MessageParam], schema: dict[str, Any]) -> str: ...


def text_of(response: Message) -> str:
    """The text blocks of a response, joined. Other blocks (tool_use, thinking) are skipped."""
    if response.stop_reason == "refusal":
        return REFUSED
    return "".join(block.text for block in response.content if block.type == "text")


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
                system=self.system_prompt,
                messages=messages,
                tools=tools,
                output_config=output_config,
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

        usage = response.usage
        LLM_TOKENS.labels("input").inc(usage.input_tokens)
        LLM_TOKENS.labels("output").inc(usage.output_tokens)
        log.info(
            "reply from %s: %d input tokens, %d output tokens",
            self.model,
            usage.input_tokens,
            usage.output_tokens,
            # Anthropic's own id for this call: what their support asks for.
            extra={"api_request_id": response._request_id},
        )
        return response

    def reply(self, messages: list[MessageParam]) -> str:
        return text_of(self._create(messages, anthropic.omit))  # no tools: one plain call

    def create(self, messages: list[MessageParam], tools: list[ToolParam]) -> Message:
        return self._create(messages, tools)

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
# How a test or a reader makes the mock answer reply_json() with exactly this text:
JSON = re.compile(r"\[mock:json (\{.*?\})\]")  # [mock:json {"title": ""}] -> '{"title": ""}'
RETRY_MARK = "Your previous answer was rejected"  # agent/titles.py starts each retry with it

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
    if not calls and "list_notes" in offered and NOTES.search(question):
        about = ABOUT.search(question)
        calls.append(("list_notes", {"search": about.group(1).strip()} if about else {}))
    if not calls and "current_time" in offered and TIME.search(question):
        calls.append(("current_time", {}))
    return calls


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
    """Returns a predictable fake reply. Free, offline, the same every time."""

    def reply(self, messages: list[MessageParam]) -> str:
        last_message = messages[-1]["content"]
        turn = (len(messages) + 1) // 2
        reply = f"[mock reply, turn {turn}] You said: {last_message}"
        # Report usage like the real client does, so the token metrics work offline too.
        sent = mock_tokens("".join(str(message["content"]) for message in messages))
        LLM_TOKENS.labels("input").inc(sent)
        LLM_TOKENS.labels("output").inc(mock_tokens(reply))
        log.debug("mock reply: %d input tokens, %d output tokens", sent, mock_tokens(reply))
        return reply

    def create(self, messages: list[MessageParam], tools: list[ToolParam]) -> Message:
        """One scripted agent step, in the same shape as a real response.

        A new question (the last message is the user's text) gets one tool_use block for each
        call wanted_calls() finds, and a plain answer when there is none. Tool results (the
        last message holds tool_result blocks) get an answer that quotes them; with
        [mock:loop] in the question, the same tool calls again, forever.
        """
        # The history and the question are plain text; each earlier step of this run added
        # two messages of blocks (the tool request and its results).
        texts = [m for m in messages if isinstance(m["content"], str)]
        questions = [m["content"] for m in texts if m["role"] == "user"]
        question, turn = str(questions[-1]), len(questions)  # the user's last text message
        step = (len(messages) - len(texts)) // 2 + 1
        calls = wanted_calls(question, {tool["name"] for tool in tools})
        last = messages[-1]["content"]
        content: list[dict[str, Any]]
        if calls and (isinstance(last, str) or LOOP in question):
            content = [
                {"type": "tool_use", "id": f"toolu_mock_{step}_{n}", "name": name, "input": args}
                for n, (name, args) in enumerate(calls, start=1)
            ]
            stop_reason = "tool_use"
        else:
            content = [{"type": "text", "text": self.answer(question, last, turn)}]
            stop_reason = "end_turn"
        message = Message.model_validate(
            {
                "id": f"msg_mock_{step}",
                "type": "message",
                "role": "assistant",
                "model": "mock",
                "content": content,
                "stop_reason": stop_reason,
                "stop_sequence": None,
                "usage": {
                    # Everything is sent again at every step, so this grows with each step.
                    "input_tokens": mock_tokens(str(messages) + str(tools)),
                    "output_tokens": mock_tokens(str(content)),
                },
            }
        )
        LLM_TOKENS.labels("input").inc(message.usage.input_tokens)
        LLM_TOKENS.labels("output").inc(message.usage.output_tokens)
        return message

    def reply_json(self, messages: list[MessageParam], schema: dict[str, Any]) -> str:
        """Scripted JSON. The k-th attempt answers with the k-th distinct [mock:json ...] in the
        messages; when there is none left, made-up values that match the schema."""
        text = " ".join(str(message["content"]) for message in messages)
        scripted: list[str] = list(dict.fromkeys(JSON.findall(text)))  # each once, in order
        attempt = text.count(RETRY_MARK)  # 0 on the first try, 1 on the retry, ...
        if attempt < len(scripted):
            answer = scripted[attempt]
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
        parts = []
        for block in last:  # the tool_result blocks the loop sent back
            if block.get("is_error"):
                parts.append(f"I tried, but the tool failed: {block['content']}")
            else:
                parts.append(f"I looked it up. The tool said:\n{block['content']}")
        return f"[mock reply, turn {turn}] " + "\n".join(parts)
