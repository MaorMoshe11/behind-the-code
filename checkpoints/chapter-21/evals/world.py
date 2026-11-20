"""The world one eval case runs in: a fresh database, a notes service in memory, and the agent.

Every case starts from nothing and builds exactly what its "setup" says, so a case gives the
same starting point on every run and on every machine. The notes service is played in this
process (the same /v1 API as notes-service/, through the real NotesClient), so the evals need
no other program running, and nothing they do touches your own notes.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx2

from agent.config import Settings
from agent.conversations import Conversations
from agent.db import make_engine
from agent.llm import AgentClient
from agent.notes import NotesClient
from agent.router import ROUTER_PROMPT, Router
from agent.team import ORCHESTRATOR_PROMPT, SPECIALISTS, Team

OWNER = "eval"  # the client every case runs as


class NotesService:
    """The notes service's API in memory. Ids are predictable: a1b2c3d1..., a1b2c3d2..., so a
    case can name a note's ref. down=True: every request fails, as when the service is down."""

    def __init__(self, down: bool = False) -> None:
        self.notes: list[dict[str, Any]] = []
        self.down = down

    def add(self, conversation_id: str, text: str) -> None:
        number = 0xA1B2C3D1 + len(self.notes)
        note = {"id": f"{number:08x}" + "0" * 24, "conversation_id": conversation_id, "text": text}
        self.notes.append(note)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("the notes service is down (eval setup)")
        if request.method == "POST":
            body = json.loads(request.content)
            self.add(body["conversation_id"], body["text"])
            return httpx2.Response(201, json={**self.notes[-1], "created_at": "2026-11-19"})
        if request.method == "DELETE":
            note_id = request.url.path.rsplit("/", 1)[-1]
            self.notes = [n for n in self.notes if n["id"] != note_id]
            return httpx2.Response(204)
        conversation = request.url.params.get("conversation_id")
        q = request.url.params.get("q", "").lower()
        found = [n for n in self.notes if n["conversation_id"] == conversation]
        found = [n for n in found if q in n["text"].lower()]
        limit = int(request.url.params.get("limit", "50"))
        return httpx2.Response(200, json=[{**n, "created_at": "2026-11-19"} for n in found][:limit])

    def client(self) -> NotesClient:
        transport = httpx2.MockTransport(self.handle)
        return NotesClient("http://notes", "eval", retries=0, backoff=0, transport=transport)


@dataclass
class World:
    conversations: Conversations
    conversation_id: str
    notes: NotesService
    approvals: list[str] = field(default_factory=list)  # what the scripted person answered


def build_world(
    setup: dict[str, Any], settings: Settings, client: AgentClient, team_client: Any
) -> World:
    """A world from a case's setup:

    notes: texts saved in the conversation. notes_down: the service fails.
    memories: facts remembered about the client. earlier: messages of an earlier conversation.
    write_tools: "0", "ask" or "1" (CHAT_WRITE_TOOLS). team: true for the router and team.
    max_steps: CHAT_MAX_STEPS for this case.
    """
    service = NotesService(down=bool(setup.get("notes_down")))
    mode = str(setup.get("write_tools", "0"))
    team = None
    if setup.get("team"):
        workers = {name: team_client(s.prompt) for name, s in SPECIALISTS.items()}
        team = Team(Router(team_client(ROUTER_PROMPT)), team_client(ORCHESTRATOR_PROMPT), workers)
    conversations = Conversations(
        client,
        settings.max_turns,
        make_engine("sqlite://"),
        service.client(),
        int(setup.get("max_steps", settings.max_steps)),
        write_tools=mode != "0",
        approve_writes=mode == "ask",
        team=team,
    )
    earlier = setup.get("earlier", [])
    if earlier:
        old = conversations.start(OWNER)
        for message in earlier:
            conversations.send(old, message)
    for fact in setup.get("memories", []):
        conversations.memory(OWNER).remember(fact)
    current = conversations.start(OWNER)
    for text in setup.get("notes", []):
        service.add(current, text)
    return World(conversations, current, service)


def memories(world: World) -> list[str]:
    return [fact.text for fact in world.conversations.memory(OWNER).recall()]
