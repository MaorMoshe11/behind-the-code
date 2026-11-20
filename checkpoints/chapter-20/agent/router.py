"""The router: one small call that decides who answers a message, the chat or the team.

Routing is a workflow step (chapter 16), not an agent: one classification, structured output,
and our code acts on it. Most messages are ordinary chat, so when in doubt, or when the
router fails, the chat answers: the cheap path is the default.
"""

import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.llm import AgentClient, LLMError
from agent.metrics import ROUTES

log = logging.getLogger(__name__)

ROUTER_PROMPT = (
    "You route the messages of a chat assistant. Answer team only when the message asks to "
    "review or collect information across several sources (the user's notes, their earlier "
    "conversations, what is remembered about them), work too big for one quick answer. "
    "Everything else is chat. Most messages are chat."
)


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: Literal["chat", "team"]
    reason: str = Field(description="A few words: why.")


SCHEMA = anthropic.transform_schema(Route.model_json_schema())


class Router:
    def __init__(self, client: AgentClient) -> None:
        self.client = client  # its own system prompt (ROUTER_PROMPT), often a smaller model

    def route(self, text: str) -> str:
        """'chat' or 'team'. Only the message is sent: no history, no tools, few tokens."""
        try:
            answer = self.client.reply_json([{"role": "user", "content": text}], SCHEMA)
            route = Route.model_validate_json(answer).route
        except (LLMError, ValidationError):
            log.warning("the router failed; the chat answers", exc_info=True)
            route = "chat"
        ROUTES.labels(route).inc()
        log.info("routed to %s", route, extra={"route": route})
        return route
