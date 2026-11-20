# Architecture

Two services in one repository. Each one owns its data: no service reads or writes the
other's database. They talk over HTTP, through a versioned API, and through events in Kafka.

| Service | Code | Data it owns | Who calls it |
|---|---|---|---|
| chat (`my-agent`) | `agent/` | conversations and messages, in its Postgres (`db`) | people: the web page, `ask.py`, the terminal |
| usage worker (part of the chat service) | `worker/`, same image | usage statistics, in its own SQLite file (`usagedata`); derived, rebuilt from the events | nobody: it reads `chat-events` |
| notes (`notes-service`) | `notes-service/` | notes, in its own Postgres (`notes-db`) | the chat service only (`/v1`, with `NOTES_API_KEY`) |

## The calls between them

The chat calls the notes service for `/note`, `/notes`, and when a conversation is deleted
(`agent/notes.py`):

- timeout 2 s per attempt (`NOTES_TIMEOUT`), 3 attempts, backoff 0.2 s and 0.4 s with jitter:
  a user waits about 7 s at most;
- every new note carries an `Idempotency-Key`; the notes service saves a key once;
- after 3 failed calls in a row the circuit breaker opens: for 30 s, `/note` answers at once.

The chat publishes events to Kafka (`chat-events`, 3 partitions, key = conversation id) and
never waits for anyone to read them. The usage worker consumes them at least once and applies
each event id once.

Deleting a conversation is an orchestrated saga in the chat (`agent/saga.py`): archive the
conversation, delete its notes, delete the conversation; on failure, compensate newest first.

## Seeing what happens

One request id follows a request everywhere: the api makes it (or keeps a well-formed
`X-Request-ID`), the notes client sends it as `X-Request-ID`, events carry it in the Kafka
header `request_id`. Every service logs JSON lines to stdout with that id. The api and the
worker expose metrics (`/metrics`, worker port 9100); Prometheus scrapes them and evaluates
`monitoring/alerts.yml`; `docs/runbook.md` says what to do for each alert.

## When something is down

| Down | What still works | What users see |
|---|---|---|
| notes | chatting, history, conversations | "Notes are unavailable right now"; deleting a conversation answers 503 and changes nothing; `/ready` 200 with `"notes": "unreachable"` |
| notes-db | the same | the same (the notes service answers 503 on `/ready`, 500 on `/v1`) |
| kafka | everything users do | nothing at once; events wait in the api's memory for up to 30 s, then are lost (logged) |
| worker | everything users do | statistics fall behind; the worker catches up when it is back (the lag) |
| chat's db | nothing in the chat; notes keep their data | errors; `/ready` 503 |

## Known gaps

- Dual write: the api saves a message, then publishes its event. If the process dies in
  between, or Kafka is down for more than 30 s, the event is lost. The fix is an outbox table
  in the chat's database, written in the same transaction, and a relay that publishes it.
- The saga keeps its progress in memory. If the api dies in the middle, a conversation can
  stay archived with its notes gone. Archived conversations older than a few minutes should be
  found and finished (deleted) by a cleanup job.
- Restored notes (a compensation) are new notes with new ids.
- A person who sends `/note` again after "unavailable" makes a new key, so a note that was
  saved after all may appear twice. Only automatic retries are protected.
- The circuit breaker lives in one process: each copy of the chat service has its own.

## Plan: an outbox for the events (not built yet)

1. Migration: a table `outbox` (id, topic, key, payload JSON, created_at, sent_at NULL).
2. `Conversations.send()` and the delete saga's last step add the event row in the same
   transaction as the messages: the event exists if and only if the change was committed.
3. A relay process (like the worker: same image, `python -m agent.relay`) reads unsent rows
   oldest first, publishes each with `acks=all`, waits for the confirmation, then sets
   `sent_at`. If it dies between the two, the row is published again: consumers must stay
   idempotent (they are: `event_id`).
4. A job deletes sent rows older than a week. Kafka's own transactions do not replace this:
   they cover Kafka writes only, not the chat's Postgres.
