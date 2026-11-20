"""The notes service's HTTP API, version 1.

Run it with: uv run uvicorn notes.api:create_app --factory --port 8100

The contract: every path starts with /v1. Inside v1, changes only add (a new endpoint, a
new optional field); a change that would break a client is a new version, /v2, served
next to /v1 until no client uses /v1.
"""

import logging
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from notes import project_version
from notes.config import Settings, load_settings
from notes.db import NoteRow, make_engine

log = logging.getLogger(__name__)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class NoteIn(BaseModel):
    """What a client sends to create a note."""

    conversation_id: str = Field(min_length=1, max_length=64, description="The chat's id.")
    text: str = Field(min_length=1, max_length=2000, description="The note itself.")


class Note(BaseModel):
    """A saved note."""

    id: str
    conversation_id: str
    text: str
    created_at: datetime


def to_note(row: NoteRow) -> Note:
    return Note(
        id=row.id, conversation_id=row.conversation_id, text=row.text, created_at=row.created_at
    )


def key_checker(expected: str) -> Callable[[str | None], None]:
    """Only callers with the key (the chat service) may use the notes."""

    def check(key: Annotated[str | None, Depends(api_key_header)]) -> None:
        if key is None or not secrets.compare_digest(key, expected):
            raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key header.")

    return check


def replay(session: Session, key: str, note: NoteIn) -> NoteRow | None:
    """The note already saved under this Idempotency-Key, if there is one."""
    row = session.scalar(select(NoteRow).where(NoteRow.idempotency_key == key))
    if row is not None and (row.conversation_id, row.text) != (note.conversation_id, note.text):
        # The same key with a different note: a bug in the client. Never guess.
        raise HTTPException(status_code=409, detail="This Idempotency-Key belongs to another note.")
    return row


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. uvicorn calls it with nothing; tests pass their own settings."""
    settings = settings or load_settings()
    if settings.delay_seconds or settings.fail_after_save:
        log.warning(
            "fault injection: delay %ss, fail after save %s",
            settings.delay_seconds,
            settings.fail_after_save,
        )
    engine = make_engine(settings.database_url)
    sessions = sessionmaker(engine)
    app = FastAPI(title="notes-service", version=project_version())

    def slow_down() -> None:
        """Fault injection: a slow service. It still does the work, only late."""
        time.sleep(settings.delay_seconds)

    # Every /v1 endpoint: the key first, then the (usually zero) delay.
    v1 = [Depends(key_checker(settings.api_key)), Depends(slow_down)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready(response: Response) -> dict[str, str]:
        info = {"version": project_version(), "environment": settings.app_env}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            response.status_code = 503
            return {"status": "not ready", "database": "unreachable", **info}
        return {"status": "ready", "database": "ok", **info}

    @app.post("/v1/notes", status_code=201, dependencies=v1)
    def add_note(
        note: NoteIn,
        response: Response,
        idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
    ) -> Note:
        """Save a note. With an Idempotency-Key, a repeated request returns the first note."""
        with sessions.begin() as session:
            if idempotency_key and (row := replay(session, idempotency_key, note)):
                response.status_code = 200  # not created now: an earlier attempt created it
                return to_note(row)
            row = NoteRow(id=uuid.uuid4().hex, idempotency_key=idempotency_key, **note.model_dump())
            session.add(row)
            # The INSERT. If two requests with one key race, the unique column refuses the
            # second (an error, 500); the client retries it, and the retry gets the replay.
            session.flush()
            saved = to_note(row)
        if settings.fail_after_save:
            # The note is saved and committed. The client never learns it.
            raise HTTPException(status_code=500, detail="Fault injection: saved, then failed.")
        return saved

    @app.get("/v1/notes", dependencies=v1)
    def list_notes(
        conversation_id: Annotated[str, Query(min_length=1, max_length=64)],
        q: Annotated[str | None, Query(max_length=200, description="Text to look for.")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[Note]:
        """The notes of one conversation, oldest first; with q, only those that contain it."""
        query = select(NoteRow).where(NoteRow.conversation_id == conversation_id)
        if q:
            query = query.where(NoteRow.text.icontains(q, autoescape=True))
        with sessions() as session:
            rows = session.scalars(query.order_by(NoteRow.created_at, NoteRow.id).limit(limit))
            return [to_note(row) for row in rows]

    @app.get("/v1/notes/{note_id}", dependencies=v1)
    def get_note(note_id: str) -> Note:
        with sessions() as session:
            row = session.get(NoteRow, note_id)
            if row is None:
                raise HTTPException(status_code=404, detail="No note with this id.")
            return to_note(row)

    @app.delete("/v1/notes/{note_id}", status_code=204, dependencies=v1)
    def delete_note(note_id: str) -> None:
        with sessions.begin() as session:
            row = session.get(NoteRow, note_id)
            if row is None:
                raise HTTPException(status_code=404, detail="No note with this id.")
            session.execute(delete(NoteRow).where(NoteRow.id == note_id))

    return app
