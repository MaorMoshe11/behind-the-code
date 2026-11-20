"""Human approval for writing tools (human in the loop).

A writing tool call stops and asks a person when every write needs approval
(CHAT_WRITE_TOOLS=ask), or when the run has already read untrusted text (a note, a memory,
an earlier conversation): from then on, what the model wants to write may have been chosen
by whoever wrote that text (prompt injection).

The person sees the exact action: the tool, its input as the model wrote it, and a preview
that OUR code computed (which note would be deleted, what would be saved). Never a summary
written by the model: the model is the party whose request is being checked.

Two ways to ask. In the terminal, a question, and the run waits for the answer. Over HTTP
the run cannot wait (the request must end), so it stops; the desk keeps the pending call,
and the client approves or rejects it with a second request (POST /approvals/{id}).
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

APPROVAL_MINUTES = 10  # a pending call older than this can no longer be approved


@dataclass(frozen=True)
class Request:
    """What the person decides on."""

    tool: str
    input: dict[str, Any]  # exactly what will run
    preview: str  # what it will change, computed by our code
    reason: str  # why it asks: every write, or untrusted text read earlier in this run

    def text(self) -> str:
        lines = [f"The agent wants to run {self.tool} with {self.input}"]
        if self.preview:
            lines.append(self.preview)
        lines.append(f"(Asking because {self.reason}.)")
        return "\n".join(lines)


Approver = Callable[[Request], bool]  # True: run it. False: do not.


def ask_in_terminal(request: Request) -> bool:
    """The terminal's approver: show the exact action, and wait for y or n."""
    print(request.text())
    answer = input("Allow it? (y/N) ").strip().lower()
    return answer in ("y", "yes")


@dataclass
class Pending:
    id: str
    conversation_id: str
    owner: str
    request: Request
    created: float = field(default_factory=time.monotonic)


class ApprovalNeeded(Exception):
    """Raised by the HTTP approver: the run stops here, and a person decides later."""

    def __init__(self, pending: Pending) -> None:
        super().__init__(pending.id)
        self.pending = pending


class ApprovalNotFound(Exception):
    """No pending call with this id for this client (decided, expired, or someone else's)."""


class ApprovalDesk:
    """Pending calls of the HTTP API, in this process's memory.

    Enough for one copy of the service. A restart forgets them (the client asks again), and
    two copies behind a load balancer would not see each other's: a production design keeps
    them in the database, with who decided and when (an audit trail).
    """

    def __init__(
        self, minutes: int = APPROVAL_MINUTES, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.seconds = minutes * 60
        self.clock = clock
        self.waiting: dict[str, Pending] = {}
        self.lock = threading.Lock()  # the API runs requests in threads

    def approver(self, conversation_id: str, owner: str, paused: list[Pending]) -> Approver:
        """An approver for one request: it records the call, adds it to `paused` (for the
        response), and stops the run."""

        def pause(request: Request) -> bool:
            pending = Pending(uuid.uuid4().hex, conversation_id, owner, request, self.clock())
            with self.lock:
                self.waiting[pending.id] = pending
            paused.append(pending)
            raise ApprovalNeeded(pending)

        return pause

    def pending(self, owner: str) -> list[Pending]:
        with self.lock:
            self.expire()
            return [p for p in self.waiting.values() if p.owner == owner]

    def take(self, approval_id: str, owner: str) -> Pending:
        """Remove and return one pending call: it can be decided once, by its owner only."""
        with self.lock:  # two decisions at the same moment: exactly one gets it
            self.expire()
            pending = self.waiting.get(approval_id)
            if pending is None or pending.owner != owner:
                raise ApprovalNotFound(approval_id)
            del self.waiting[approval_id]
            return pending

    def expire(self) -> None:
        now = self.clock()
        for key in [k for k, p in self.waiting.items() if now - p.created > self.seconds]:
            self.waiting.pop(key, None)
