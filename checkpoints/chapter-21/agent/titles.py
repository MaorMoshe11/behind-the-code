"""A better title for a conversation, from the model: data, not prose (structured output).

The model is asked for JSON that matches TitleSuggestion's schema. The API keeps the answer
to the schema's shape; what the API cannot check (here: the title's length) Pydantic checks.
A rejected answer gets one retry with the reasons; after that, the rule-based title stays.
"""

import logging
from typing import Literal

import anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.llm import RETRY_MARK, AgentClient

log = logging.getLogger(__name__)
TITLE_LENGTH = 50  # the same limit as the automatic titles (agent/conversations.py)
ATTEMPTS = 2  # the first answer, and one retry with the reasons it was rejected

PROMPT = (
    "Suggest a title for the conversation below: a few words that say what it is about, "
    f"at most {TITLE_LENGTH} characters, no quotes. Also choose its topic.\n\n"
)


class TitleSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1,
        max_length=TITLE_LENGTH,
        description=f"A short title, at most {TITLE_LENGTH} characters.",
    )
    topic: Literal["code", "work", "study", "personal", "other"]


def title_schema() -> dict[str, object]:
    """The JSON schema the API gets. transform_schema (from the SDK) removes what structured
    outputs do not support, such as minLength and maxLength; we check those ourselves."""
    return anthropic.transform_schema(TitleSuggestion.model_json_schema())


def transcript(messages: list[MessageParam]) -> str:
    """The conversation as plain text: who said what."""
    return "\n".join(f"{message['role']}: {message['content']}" for message in messages)


def suggest_title(client: AgentClient, messages: list[MessageParam]) -> TitleSuggestion | None:
    """The model's suggestion, validated; None when it did not fit, even after a retry."""
    question = PROMPT + transcript(messages)
    for attempt in range(1, ATTEMPTS + 1):
        answer = client.reply_json([{"role": "user", "content": question}], title_schema())
        try:
            return TitleSuggestion.model_validate_json(answer)
        except ValidationError as error:
            reasons = "; ".join(
                f"{'.'.join(str(part) for part in problem['loc']) or 'answer'}: {problem['msg']}"
                for problem in error.errors()
            )
            log.warning(
                "title suggestion rejected: %s", reasons, extra={"attempt": attempt}
            )  # the reasons only: never the conversation's text
            # A new request with the reasons, not an edited conversation: simple, and honest.
            question = f"{RETRY_MARK}: {reasons}. Answer again.\n\n{PROMPT}{transcript(messages)}"
    return None
