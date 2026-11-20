"""The agent as an HTTP service.

Run it with: uv run uvicorn agent.api:create_app --factory
"""

import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path as FilePath
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent import logs, metrics, project_version, saga
from agent.config import SYSTEM_PROMPT, ConfigError, Settings, load_settings
from agent.conversations import ConversationNotFound, Conversations
from agent.db import make_engine
from agent.events import Events, KafkaEvents, event, make_events
from agent.llm import AgentClient, ClaudeClient, LLMError, MockClient
from agent.notes import NotesUnavailable, make_notes, note_command
from agent.security import DEFAULT_CLIENT, RateLimiter, hash_key

log = logging.getLogger(__name__)
CHAT_PAGE = FilePath(__file__).parent / "static" / "chat.html"

# Clients prove who they are with this header. auto_error=False: we write the 401 ourselves.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer = HTTPBearer(auto_error=False)  # Authorization: Bearer <token>, for /metrics

# Ids are made by start(): 32 hex characters. Anything else is refused before any work.
CONVERSATION_ID = r"^[0-9a-f]{32}$"
ConversationId = Annotated[str, Path(pattern=CONVERSATION_ID)]
MAX_BODY = 64 * 1024  # bytes; a message is at most 4000 characters


class ChatRequest(BaseModel):
    """What a client sends to POST /chat."""

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(
        default=None,
        pattern=CONVERSATION_ID,
        description="Leave it out to start a new conversation.",
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


def make_client(settings: Settings) -> AgentClient:
    """The mock or the real client. A server cannot ask questions, so it refuses to start."""
    if settings.mock:
        return MockClient()
    if not settings.api_key:
        raise ConfigError("ANTHROPIC_API_KEY is not set (or set CHAT_MOCK=1).")
    return ClaudeClient(settings.model, SYSTEM_PROMPT)


def key_checker(clients: dict[str, str]) -> Callable[[str | None], str]:
    """Build the dependency that says who is calling: no key, or an unknown key, gets 401."""

    def check(key: Annotated[str | None, Depends(api_key_header)]) -> str:
        # We look up the key's hash, never the key itself. A wrong key changes its whole
        # hash, so how long the lookup takes reveals nothing about the right keys.
        client = clients.get(hash_key(key)) if key else None
        if client is None:
            raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key header.")
        return client

    return check


def create_app(
    settings: Settings | None = None,
    client: AgentClient | None = None,
    events: Events | None = None,
) -> FastAPI:
    """Build the app. uvicorn calls it with nothing; tests pass their own settings and client."""
    if settings is None:
        load_dotenv()
        settings = load_settings()
        logs.setup_logging(settings.log_level, "chat-api")
    clients = dict(settings.api_clients)  # {sha256 of a key: the client's name}
    if settings.agent_api_key:  # the single key of chapters 5 to 13: the "default" client
        clients[hash_key(settings.agent_api_key)] = DEFAULT_CLIENT
    if not clients:
        # Fail closed: a server without a key would let anyone spend your API credit.
        raise ConfigError("AGENT_API_KEY is not set. Put a long random value in .env.")
    log.info("starting my-agent %s, environment %s", project_version(), settings.app_env)
    engine = make_engine(settings.database_url)
    notes = make_notes(settings)
    conversations = Conversations(
        client or make_client(settings),
        settings.max_turns,
        engine,
        notes,
        settings.max_steps,
        settings.write_tools,
    )
    if events is None:
        events = make_events(settings)  # None when KAFKA_BOOTSTRAP_SERVERS is not set
    Caller = Annotated[str, Depends(key_checker(clients))]  # the client's name
    limiter = RateLimiter(settings.rate_limit)

    def own(conversation_id: str, caller: str) -> None:
        """Authorization: only the owner may touch a conversation. Others get 404, not 403,
        so they cannot even learn that the id exists."""
        if conversations.owner(conversation_id) != caller:
            raise ConversationNotFound(conversation_id)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if isinstance(events, KafkaEvents):
            events.close()  # on shutdown, send the events that are still queued

    app = FastAPI(title="my-agent", version=project_version(), lifespan=lifespan)

    # Requests that run every few seconds and say nothing new: logged only at DEBUG.
    quiet = {"/health", "/ready", "/metrics"}

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Every request: an id, one access log line, and its metrics."""
        # The edge of the system: here the request gets the id that follows it everywhere.
        token = logs.request_id.set(logs.new_request_id(request.headers.get("X-Request-ID")))
        start = time.perf_counter()
        status = 500  # what the client gets if the endpoint raises
        try:
            # Refuse a huge body before reading it. (A body sent in chunks, without a
            # Content-Length, is not caught here: a proxy in front of the service limits it.)
            if int(request.headers.get("content-length") or 0) > MAX_BODY:
                response: Response = JSONResponse(
                    {"detail": "Request body too large."}, status_code=413
                )
            else:
                response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = logs.request_id.get() or ""
            return response
        finally:
            seconds = time.perf_counter() - start
            # The route template (/conversations/{conversation_id}), not the URL: metric
            # labels must take a few values only.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            metrics.observe_request(request.method, route, status, seconds)
            log.log(
                logging.DEBUG if route in quiet else logging.INFO,
                "%s %s %s",
                request.method,
                request.url.path,
                status,
                extra={"status": status, "duration_ms": round(seconds * 1000)},
            )
            logs.request_id.reset(token)

    def publish(kind: str, conversation_id: str, **fields: int) -> None:
        if events is not None:
            events.publish(event(kind, conversation_id, **fields))

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

    @app.get("/metrics", include_in_schema=False)
    def metrics_page(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Response:
        """Every metric of this process, in the Prometheus text format. Only with the token:
        the numbers tell an outsider how many users there are and what fails."""
        if settings.metrics_token is None:
            raise HTTPException(status_code=404, detail="Not Found")  # off unless configured
        token = credentials.credentials if credentials else ""
        if not secrets.compare_digest(token, settings.metrics_token):
            raise HTTPException(status_code=401, detail="Missing or wrong metrics token.")
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/chat")
    def chat(request: ChatRequest, caller: Caller) -> ChatResponse:
        """Send one message. The reply comes back with the conversation's id."""
        wait = limiter.check(caller)  # every model call costs money: a limit per client
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many messages. Wait a little and try again.",
                headers={"Retry-After": str(wait)},
            )
        conversation_id = request.conversation_id or conversations.start(caller)
        try:
            own(conversation_id, caller)  # 404 for an unknown id, or someone else's
            turns = len(conversations.messages(conversation_id)) // 2
            # /note and /notes go to the notes service; anything else goes to the model.
            reply = note_command(notes, conversation_id, request.message)
            if reply is None:
                reply = conversations.send(conversation_id, request.message)
                turns += 1
                # Saved: now tell whoever is interested. Queued in memory, so it costs nothing.
                publish(
                    "message.created",
                    conversation_id,
                    user_chars=len(request.message),
                    reply_chars=len(reply),
                )
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="No conversation with this id.") from None
        except LLMError as error:
            log.exception("request failed")
            raise HTTPException(status_code=502, detail=str(error)) from error
        return ChatResponse(conversation_id=conversation_id, reply=reply, turns=turns)

    @app.get("/conversations")
    def list_conversations(caller: Caller) -> list[ConversationSummary]:
        """The caller's newest conversations, newest first, with their titles."""
        return [
            ConversationSummary(conversation_id=conversation_id, title=title)
            for conversation_id, title in conversations.newest(user_id=caller)
        ]

    @app.get("/conversations/{conversation_id}")
    def get_conversation(conversation_id: ConversationId, caller: Caller) -> ConversationOut:
        """The messages the agent still remembers in one conversation."""
        try:
            own(conversation_id, caller)
            messages = conversations.messages(conversation_id)
            title = conversations.title(conversation_id)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="No conversation with this id.") from None
        return ConversationOut(
            conversation_id=conversation_id,
            title=title,
            messages=[Message.model_validate(message) for message in messages],
        )

    @app.delete("/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: ConversationId, caller: Caller) -> None:
        """Delete a conversation, and its notes in the notes service: a saga."""
        try:
            own(conversation_id, caller)
            saga.run_saga("delete", saga.delete_conversation(conversations, notes, conversation_id))
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="No conversation with this id.") from None
        except NotesUnavailable:
            # Compensated: the conversation is back, as it was. The user may simply try again.
            raise HTTPException(
                status_code=503,
                detail="The notes service is unavailable, so nothing was deleted. Try again later.",
            ) from None
        publish("conversation.deleted", conversation_id)

    @app.get("/", include_in_schema=False)
    def chat_page() -> FileResponse:
        """The web chat page. It is not part of the API, so Swagger does not list it."""
        return FileResponse(CHAT_PAGE)

    return app
