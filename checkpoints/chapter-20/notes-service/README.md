# notes-service

Short notes attached to the conversations of the chat service (`my-agent`). A separate
service: its own project, database, image and version. The chat service is its only client.

## Run

```powershell
uv sync
$env:NOTES_API_KEY = "<a long random value; the chat service sends the same one>"
uv run uvicorn notes.api:create_app --factory --port 8100
```

| Variable | What it does | Default |
|---|---|---|
| `NOTES_API_KEY` (or `NOTES_API_KEY_FILE`) | The key callers must send in `X-API-Key`. Required. | none |
| `DATABASE_URL` | The notes database (SQLAlchemy URL). The table is created at startup. | `sqlite:///notes.db` |
| `DATABASE_PASSWORD` (or `_FILE`) | The password, when it is not in `DATABASE_URL`. | none |
| `APP_ENV` | `local`, `staging` or `prod`. | `local` |
| `NOTES_DELAY_SECONDS` | Fault injection: every `/v1` request waits this long. Refused in prod. | `0` |
| `NOTES_FAIL_AFTER_SAVE` | Fault injection: `1` = save the note, then answer 500. Refused in prod. | `0` |

## API, version 1

| Endpoint | What it does |
|---|---|
| `POST /v1/notes` | `{"conversation_id", "text"}` -> the note, 201. With an `Idempotency-Key` header, a repeat returns the first note (200); the same key with another note is 409. |
| `GET /v1/notes?conversation_id=...&q=...&limit=50` | The notes of a conversation, oldest first; `q` keeps those that contain it. |
| `GET /v1/notes/{id}` | One note, or 404. |
| `DELETE /v1/notes/{id}` | 204, or 404. |
| `DELETE /v1/notes?conversation_id=...` | Delete every note of a conversation; 200 with the deleted notes (`[]` when none). Added in 0.2.0. |
| `GET /health`, `GET /ready` | Liveness, and readiness (the database answers). No key. |

Inside v1, changes only add (an endpoint, an optional field). Anything that would break the
chat service is `/v2`, served next to `/v1`. `tests/test_contract.py` guards v1.

## Checks

```powershell
uv run ruff check
uv run ruff format --check
uv run mypy notes
uv run pytest
```

The image: `docker build -t my-agent-notes:0.2.0 .` (from this folder).

## Logs

JSON lines on standard output. A caller's `X-Request-ID` (the chat sends one) is kept and
written into every line of that request, and returned in the answer. Saved, replayed and
deleted notes are logged by id and count, never by text.
