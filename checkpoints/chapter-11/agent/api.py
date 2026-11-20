"""The agent as an HTTP service.

Run it with: uv run uvicorn agent.api:create_app --factory
"""

import logging
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent import project_version
from agent.cli import setup_logging
from agent.config import SYSTEM_PROMPT, ConfigError, Settings, load_settings
from agent.conversations import ConversationNotFound, Conversations
from agent.db import make_engine
from agent.llm import ChatClient, ClaudeClient, LLMError, MockClient
from agent.notes import make_notes, note_command

log = logging.getLogger(__name__)
CHAT_PAGE = Path(__file__).parent / "static" / "chat.html"

# Clients prove who they are with this header. auto_error=False: we write the 401 ourselves.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class ChatRequest(BaseModel):
    """What a client sends to POST /chat."""

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None, description="Leave it out to start a new conversation."
    )


class ChatResponse(BaseModel):
    """What POST /chat sends back."""

    conversation_id: str
    reply: str
    turns: int = Field(description="How many turns the agent remembers in this conversation.")


class Message(BaseModel):
    """One message in a conversation."""

    role: Literal["user", "assistant"]
    content: str


class ConversationOut(BaseModel):
    """What GET /conversations/{conversation_id} sends back."""

    conversation_id: str
    title: str
    messages: list[Message]


class ConversationSummary(BaseModel):
    """One line in the list of conversations."""

    conversation_id: str
    title: str


def make_client(settings: Settings) -> ChatClient:
    """The mock or the real client. A server cannot ask questions, so it refuses to start."""
    if settings.mock:
        return MockClient()
    if not settings.api_key:
        raise ConfigError("ANTHROPIC_API_KEY is not set (or set CHAT_MOCK=1).")
    return ClaudeClient(settings.model, SYSTEM_PROMPT)


def key_checker(expected: str) -> Callable[[str | None], None]:
    """Build the dependency that guards an endpoint: no key, or a wrong key, gets 401."""

    def check(key: Annotated[str | None, Depends(api_key_header)]) -> None:
        # compare_digest takes the same time for every wrong key, so timing reveals nothing.
        if key is None or not secrets.compare_digest(key, expected):
            raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key header.")

    return check


def create_app(settings: Settings | None = None, client: ChatClient | None = None) -> FastAPI:
    """Build the app. uvicorn calls it with nothing; tests pass their own settings and client."""
    if settings is None:
        load_dotenv()
        settings = load_settings()
        setup_logging(settings.log_level)
    if not settings.agent_api_key:
        # Fail closed: a server without a key would let anyone spend your API credit.
        raise ConfigError("AGENT_API_KEY is not set. Put a long random value in .env.")
    log.info("starting my-agent %s, environment %s", project_version(), settings.app_env)
    engine = make_engine(settings.database_url)
    conversations = Conversations(client or make_client(settings), settings.max_turns, engine)
    notes = make_notes(settings)
    require_key = Depends(key_checker(settings.agent_api_key))
    app = FastAPI(title="my-agent", version=project_version())

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness: the process answers. It checks nothing else, so a restart could fix it."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready(response: Response) -> dict[str, str]:
        """Readiness: can this copy serve a chat right now? It needs the database for that."""
        info = {"version": project_version(), "environment": settings.app_env}
        # Notes are reported, never required: without them the chat still works, so a notes
        # outage must not take this copy out of service.
        if notes is not None:
            info["notes"] = "ok" if notes.ready() else "unreachable"
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            log.warning("not ready: the database does not answer")
            response.status_code = 503
            return {"status": "not ready", "database": "unreachable", **info}
        return {"status": "ready", "database": "ok", **info}

    @app.post("/chat", dependencies=[require_key])
    def chat(request: ChatRequest) -> ChatResponse:
        """Send one message. The reply comes back with the conversation's id."""
        conversation_id = request.conversation_id or conversations.start()
        try:
            turns = len(conversations.messages(conversation_id)) // 2  # 404 for an unknown id
            # /note and /notes go to the notes service; anything else goes to the model.
            reply = note_command(notes, conversation_id, request.message)
            if reply is None:
                reply = conversations.send(conversation_id, request.message)
                turns += 1
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="No conversation with this id.") from None
        except LLMError as error:
            log.exception("request failed")
            raise HTTPException(status_code=502, detail=str(error)) from error
        return ChatResponse(conversation_id=conversation_id, reply=reply, turns=turns)

    @app.get("/conversations", dependencies=[require_key])
    def list_conversations() -> list[ConversationSummary]:
        """The newest conversations, newest first, with their titles."""
        return [
            ConversationSummary(conversation_id=conversation_id, title=title)
            for conversation_id, title in conversations.newest()
        ]

    @app.get("/conversations/{conversation_id}", dependencies=[require_key])
    def get_conversation(conversation_id: str) -> ConversationOut:
        """The messages the agent still remembers in one conversation."""
        try:
            messages = conversations.messages(conversation_id)
            title = conversations.title(conversation_id)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="No conversation with this id.") from None
        return ConversationOut(
            conversation_id=conversation_id,
            title=title,
            messages=[Message.model_validate(message) for message in messages],
        )

    @app.delete("/conversations/{conversation_id}", status_code=204, dependencies=[require_key])
    def delete_conversation(conversation_id: str) -> None:
        """Forget a conversation. The API version of /reset in the terminal."""
        try:
            conversations.delete(conversation_id)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="No conversation with this id.") from None

    @app.get("/", include_in_schema=False)
    def chat_page() -> FileResponse:
        """The web chat page. It is not part of the API, so Swagger does not list it."""
        return FileResponse(CHAT_PAGE)

    return app
