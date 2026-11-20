# Changelog

Every release of my-agent, newest first. Versions follow semantic versioning
(MAJOR.MINOR.PATCH); while the major version is 0, the API may still change.
New changes go under "Unreleased" in the pull request that makes them.

## [Unreleased]

### Fixed
- A title cut after a word that ends in a dot (`2.`) no longer ends in four dots (AGENT-44).
  Titles made before keep theirs.

## [0.15.0] - 2026-11-19

### Added
- `docs/security.md`: the threat model, what is protected and the known gaps.
- `scripts/injection_lab.py`: SQL injection shown on a table in memory.

### Changed
- The chat image is built in two stages: no uv inside (371 MB down to 286 MB).
  `tests/test_python_version.py` checks every `FROM`, not only the first.

### Fixed
- Conversation titles are one line, at most 50 characters, cut after a whole word, with
  `...` when something was cut (AGENT-42). Migration `0008` gives the same titles to existing
  conversations; it reads them in Python, so it cannot run with `--sql`.

## [0.14.0] - 2026-11-18

### Added
- Keys per client: `AGENT_API_KEYS` holds `name:sha256` entries, so the server never stores a
  key. `scripts/new_key.py` makes a key and its entry. `AGENT_API_KEY` stays, as the client
  `default`.
- `/chat` is limited per client (`CHAT_RATE_LIMIT`, 30 per minute): then 429 with `Retry-After`.
- CI job "Secrets and known vulnerabilities": gitleaks over the whole history, and
  `uv audit --locked` for both services.

### Changed
- A conversation belongs to the client that started it (`user_id`, migration `0007`, which
  gives every older conversation to `default`). Another client's conversation answers 404, and
  `GET /conversations` lists only the caller's own.
- `GET /metrics` needs `Authorization: Bearer <METRICS_TOKEN>`; without the setting it answers
  404. Prometheus in `compose.yaml` reads the token as a secret.
- Conversation ids must be 32 hex characters (422 otherwise); bodies over 64 KiB get 413.
- The images run as the user `app`, not root. After upgrading, the worker's volume must be
  given to `app` once (see README, "Security"). Notes service 0.3.1: the same, nothing else.
- Deploy: the api gets only key hashes (`api_clients.txt`); `deploy.py` uses `deploy_key.txt`.
  The worker gets `APP_ENV` and refuses `WORKER_CRASH_BEFORE_COMMIT` in prod.
- The chat page keeps the key in `sessionStorage` (forgotten when the tab closes), and deletes
  the copy that older versions left in `localStorage`.
- Every GitHub action is pinned to a commit SHA.

### Fixed
- Deleting a conversation no longer loses its notes when the notes service deletes them but
  answers too late (a timeout): the saga now remembers the notes before deleting, and also
  compensates the step that failed, putting back whatever is missing.

## [0.13.0] - 2026-11-18

### Added
- A request id for every request: taken from `X-Request-ID` (when it looks like an id) or made
  by the api, returned in the answer, passed to the notes service and into every Kafka event
  (header `request_id`). `scripts/ask.py` prints it, the chat page shows it with an error.
- `GET /metrics` in the Prometheus text format: requests, latency, model latency and tokens,
  notes calls and the circuit breaker, events, sagas. The worker serves its metrics on port
  9100, including its consumer lag.
- Prometheus in `compose.yaml` (`--profile monitoring`), alert rules in `monitoring/alerts.yml`,
  `docs/runbook.md` (one entry per alert) and `docs/postmortem-template.md`.
- Notes service 0.3.0: JSON logs with the caller's request id, and a line per note saved,
  replayed or deleted (ids and counts only).

### Changed
- Logs are JSON lines on standard output in the api, the worker and the notes service
  (`agent.log` remains for the terminal chat only). Health checks are logged at DEBUG.
- Model errors are told apart: a timeout and a rate limit get their own message, and every
  failure is counted by reason. The mock client reports token usage too.

## [0.12.0] - 2026-11-18

### Added
- Events: the api publishes `message.created` and `conversation.deleted` to the Kafka topic
  `chat-events` (key: the conversation id) when `KAFKA_BOOTSTRAP_SERVERS` is set. Unset, nothing
  is published and nothing needs Kafka.
- The usage worker (`python -m worker`, same image): reads the events in the consumer group
  `usage-worker`, commits after the work, applies every event once (`processed_events`), and
  parks messages it cannot read in `chat-events-dlq`. `python -m worker stats` prints the result.
- Kafka (one broker, KRaft), a `topics` step and the worker in `compose.yaml` and in `deploy/`.
- Deleting a conversation is a saga (`agent/saga.py`): archive the conversation, delete its
  notes, delete the conversation. If the notes cannot be deleted, the conversation comes back
  and `DELETE /conversations/{id}` answers 503. Migration `0006` adds `archived_at`.
- Notes service 0.2.0: `DELETE /v1/notes?conversation_id=...`.
- A nightly usage report: `python -m pipelines.usage_report`, and the Airflow DAG
  `dags/daily_usage_report.py` that runs the same functions.
- A circuit breaker in front of the notes service: after 3 failed calls in a row, `/note`
  answers at once for 30 seconds instead of waiting for every timeout.
- Contract tests for the notes service's v1 API (`notes-service/tests/test_contract.py`).
- `docs/architecture.md`: the services, who owns which data, and what happens when one is down.

### Changed
- An archived conversation is hidden: 404 on its endpoints, left out of `GET /conversations`.

## [0.11.0] - 2026-11-18

### Added
- A second service, `notes-service/` (version 0.1.0): short notes per conversation, with its
  own code, database, image and tests, and a versioned API (`/v1/notes`).
- `/note <text>` and `/notes` in the chat (terminal and `POST /chat`), through
  `agent/notes.py`: a 2-second timeout (`NOTES_TIMEOUT`), retries with backoff and jitter,
  and an `Idempotency-Key` per note. When the notes service is down, the chat still answers.
- `NOTES_URL`, `NOTES_API_KEY` (or `NOTES_API_KEY_FILE`). `/ready` reports `notes`, but
  does not depend on it.
- The notes service in `compose.yaml`, in `deploy/` (`NOTES_IMAGE_TAG`, two new secrets)
  and in CI (a `notes` job, and its image).

## [0.10.0] - 2026-11-18

### Added
- `GET /ready`: readiness, 503 when the database does not answer (`/health` stays liveness).
  The image checks itself with it (`HEALTHCHECK`), and reports its version and environment.
- `APP_ENV` (`local`, `staging`, `prod`). Outside `local`, `DATABASE_URL` is required.
- Secrets from files: `<NAME>_FILE` for `ANTHROPIC_API_KEY`, `AGENT_API_KEY` and the new
  `DATABASE_PASSWORD`.
- `deploy/`: staging and prod on this computer, with `scripts/make_secrets.py` and
  `scripts/deploy.py` (deploy, check, roll back).

### Changed
- On Postgres, a connection attempt gives up after 3 seconds, and pooled connections are
  checked before use.

## [0.9.0] - 2026-11-18

### Added
- CI on GitHub Actions: lint, type check and tests (also on Postgres) and an image build
  on every pull request (`.github/workflows/ci.yml`).
- `scripts/ci_local.py` runs the same commands on your computer.
- A release workflow: a tag `vX.Y.Z` builds the image `ghcr.io/<owner>/<repo>:X.Y.Z` and
  creates a GitHub release with these notes.

### Changed
- One Python version, 3.13, written in `.python-version` and used by uv, CI and the image.
- The API reports the version from `pyproject.toml` (it was written in `api.py` by hand).

## [0.8.0] - 2026-11-18

### Added
- A Dockerfile and `compose.yaml`: the API, its migrations and Postgres in containers.
- `scripts/copy_conversations.py`, and the migration tests on Postgres (`TEST_DATABASE_URL`).

Earlier versions were not recorded here.
