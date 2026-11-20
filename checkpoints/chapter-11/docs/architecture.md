# Architecture

Two services in one repository. Each one owns its data: no service reads or writes the
other's database. They talk only over HTTP, through a versioned API.

| Service | Code | Data it owns | Who calls it |
|---|---|---|---|
| chat (`my-agent`) | `agent/` | conversations and messages, in its Postgres (`db`) | people: the web page, `ask.py`, the terminal |
| notes (`notes-service`) | `notes-service/` | notes, in its own Postgres (`notes-db`) | the chat service only (`/v1`, with `NOTES_API_KEY`) |

## The one call between them

The chat calls the notes service for `/note` and `/notes` only (`agent/notes.py`):

- timeout 2 s per attempt (`NOTES_TIMEOUT`), 3 attempts, backoff 0.2 s and 0.4 s with jitter:
  a user waits about 7 s at most;
- every new note carries an `Idempotency-Key`; the notes service saves a key once;
- after 3 failed calls in a row the circuit breaker opens: for 30 s, `/note` answers at once.

## When something is down

| Down | What still works | What users see |
|---|---|---|
| notes | chatting, history, conversations | "Notes are unavailable right now"; `/ready` 200 with `"notes": "unreachable"` |
| notes-db | the same | the same (the notes service answers 503 on `/ready`, 500 on `/v1`) |
| chat's db | nothing in the chat; notes keep their data | errors; `/ready` 503 |

## Known gaps

- Deleting a conversation does not delete its notes: two databases, no shared transaction.
  The notes stay, attached to an id that no longer exists (chapter 12).
- A person who sends `/note` again after "unavailable" makes a new key, so a note that was
  saved after all may appear twice. Only automatic retries are protected.
- The circuit breaker lives in one process: each copy of the chat service has its own.
