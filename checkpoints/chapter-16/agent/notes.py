"""The notes service, seen from the chat: a small typed client, and the /note commands.

This is the only module that knows the notes service speaks HTTP, and the only place that
decides what to do when it is slow, down, or failing.
"""

import logging
import random
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2

from agent.config import Settings
from agent.logs import request_id
from agent.metrics import NOTES_CALLS, NOTES_CIRCUIT_OPEN

log = logging.getLogger(__name__)
# Statuses that may pass if we ask again: overloaded, or failing for a moment.
RETRY_STATUSES = {429, 500, 502, 503, 504}


class NotesUnavailable(Exception):
    """The notes service gave no answer we can use: down, too slow, or failing."""


@dataclass(frozen=True)
class Note:
    id: str
    text: str


def to_note(data: dict[str, Any]) -> Note:
    """Take the fields we use from the service's JSON; ignore any field added later."""
    return Note(id=data["id"], text=data["text"])


class CircuitBreaker:
    """After `threshold` failed calls in a row, stop calling for `cooldown` seconds.

    Closed: calls go through. Open: every call fails at once, without waiting. After the
    cooldown, one call may try (half-open): success closes the breaker, failure opens it again.
    """

    def __init__(
        self,
        threshold: int = 3,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.clock = clock  # tests pass a fake clock
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        return self.opened_at is None or self.clock() - self.opened_at >= self.cooldown

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self.clock()


class NotesClient:
    """Calls the notes service's /v1 API, with a timeout, retries and a circuit breaker."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 2.0,
        retries: int = 2,
        backoff: float = 0.2,
        transport: httpx2.BaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        # Tests pass a fake transport, so they never open a connection.
        self.http = httpx2.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,  # seconds to connect, and seconds to wait for each read
            transport=transport,
        )
        self.retries = retries
        self.backoff = backoff
        self.breaker = breaker or CircuitBreaker()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """One call, tried up to 1 + retries times. The JSON of the answer."""
        if not self.breaker.allow():
            NOTES_CALLS.labels("rejected").inc()
            raise NotesUnavailable(f"{method} {path}: circuit open, not calling for now")
        # Pass the request id on: the notes service writes it into its own log lines.
        headers = dict(kwargs.pop("headers", {}))
        current = request_id.get()
        if current:
            headers["X-Request-ID"] = current
        try:
            return self._attempts(method, path, headers=headers, **kwargs)
        finally:
            NOTES_CIRCUIT_OPEN.set(0 if self.breaker.opened_at is None else 1)

    def _attempts(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in range(self.retries + 1):
            try:
                response = self.http.request(method, path, **kwargs)
            except httpx2.TransportError as error:  # refused, timed out, connection cut
                problem = repr(error)
            else:
                if response.status_code not in RETRY_STATUSES:
                    self.breaker.success()  # it answered: the service itself is fine
                    if response.is_error:  # 4xx: our request is wrong; again will not help
                        NOTES_CALLS.labels("failed").inc()
                        raise NotesUnavailable(f"{method} {path}: {response.status_code}")
                    NOTES_CALLS.labels("ok").inc()
                    return response.json()
                problem = f"status {response.status_code}"
            if attempt < self.retries:
                # Exponential backoff (0.2 s, 0.4 s, ...) with full jitter: a random part
                # of it, so many clients that failed together do not return together.
                delay = random.uniform(0, self.backoff * 2**attempt)
                log.warning("notes: %s %s: %s; retry in %.2f s", method, path, problem, delay)
                time.sleep(delay)
        self.breaker.failure()
        NOTES_CALLS.labels("failed").inc()
        raise NotesUnavailable(f"{method} {path}: {problem}, {self.retries + 1} attempts")

    def add(self, conversation_id: str, text: str) -> Note:
        body = {"conversation_id": conversation_id, "text": text}
        # One key for this note, sent with every attempt: the service saves it only once.
        headers = {"Idempotency-Key": uuid.uuid4().hex}
        return to_note(self._request("POST", "/v1/notes", json=body, headers=headers))

    def delete_all(self, conversation_id: str) -> list[Note]:
        """Delete every note of a conversation. Returns the deleted notes (a repeat: [])."""
        found = self._request("DELETE", "/v1/notes", params={"conversation_id": conversation_id})
        return [to_note(item) for item in found]

    def restore(self, conversation_id: str, notes: Sequence[Note]) -> None:
        """Save these notes again: the compensation of delete_all. New notes, new ids."""
        for note in notes:
            body = {"conversation_id": conversation_id, "text": note.text}
            # The key comes from the old note, so running this twice restores each note once.
            headers = {"Idempotency-Key": f"restore-{note.id}"}
            self._request("POST", "/v1/notes", json=body, headers=headers)

    def list(self, conversation_id: str, q: str | None = None) -> list[Note]:
        """The notes of a conversation, oldest first; only those containing `q`, if given."""
        params = {"conversation_id": conversation_id}
        if q:
            params["q"] = q
        found = self._request("GET", "/v1/notes", params=params)
        return [to_note(item) for item in found]

    def ready(self) -> bool:
        """Is the notes service ready? One quick try, no retries: for /ready."""
        try:
            return self.http.get("/ready", timeout=1.0).status_code == 200
        except httpx2.TransportError:
            return False


def make_notes(settings: Settings) -> NotesClient | None:
    """The client, or None when this agent has no notes service (NOTES_URL not set)."""
    if not settings.notes_url:
        return None
    return NotesClient(settings.notes_url, settings.notes_api_key or "", settings.notes_timeout)


def note_command(notes: NotesClient | None, conversation_id: str, text: str) -> str | None:
    """The reply to /note <text> or /notes; None when `text` is neither (a normal message)."""
    if text != "/notes" and not text.startswith("/note "):
        return None
    if notes is None:
        return "Notes are not set up here (NOTES_URL is not set)."
    try:
        if text == "/notes":
            saved = notes.list(conversation_id)
            if not saved:
                return "No notes in this conversation yet."
            return "\n".join(f"- {note.text}" for note in saved)
        note_text = text.removeprefix("/note ").strip()
        if not note_text:
            return "Write the note after /note, for example: /note buy milk"
        note = notes.add(conversation_id, note_text)
        return f"Noted: {note.text}"
    except NotesUnavailable:
        # Graceful degradation: the chat goes on; only notes are missing for now.
        log.exception("notes unavailable")
        return "Notes are unavailable right now (the chat still works). Try again later."
