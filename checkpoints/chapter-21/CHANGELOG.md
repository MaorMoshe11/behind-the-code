# Changelog

Every release of my-agent, newest first. Versions follow semantic versioning
(MAJOR.MINOR.PATCH). From 1.0.0 on, the HTTP API, the CLI commands and the environment
variables are the public interface: a change that breaks them needs a new major version.
New changes go under "Unreleased" in the pull request that makes them.

## [Unreleased]

## [1.0.0] - 2026-11-20

The first stable release: the interface that 0.x grew (the HTTP API, the CLI and its
commands, the environment variables) is now a promise.

### Added
- Agent evals (`evals/`): a dataset of cases, a runner (`python -m evals.run`) with a pass
  rate, repeated runs, saved results and `--compare`; code graders on the answer, the
  trajectory and the state; a model judge for rubrics, and `--calibrate` against human
  labels. CI runs the offline evals against the mock.
- Traces (`agent/tracing.py`): every message is a tree of spans (router, orchestrator,
  subagents, model calls, tool calls) with time, tokens and dollars; `CHAT_TRACE_DIR` saves
  them; `python -m agent.tracing <file>` prints one. A failed eval run keeps its trace.
- Cost: `agent/prices.toml` (prices per model, with the date checked) and `agent/cost.py`;
  `llm_cost_dollars_total{client,agent}`; `tokens`, `cost_usd`, `conversation_id` and
  `prompt_version` in every `"model replied"` line; the alert `ModelSpendHigh`.
- Approvals for writing tools (ADR 0006): `CHAT_WRITE_TOOLS=ask`; the terminal asks y/N; the
  API answers with `approval`, `GET /approvals` and `POST /approvals/{id}` decide. In every
  mode, a write after untrusted text was read in the run needs a person.
- Results of `list_notes`, `recall` and `search_conversations` are marked `<untrusted>`, and
  the system prompt says such text is data.
- Guardrails (`agent/guardrails.py`): a message with a secret key is refused (422 in the API);
  a reply is cleaned of anything that looks like one. `guardrail_blocks_total`.
- The real client sends adaptive thinking with `CHAT_EFFORT` (default `medium`) and retries a
  refusal once on `CHAT_FALLBACK_MODEL` (default `claude-opus-4-8`, `off` to disable);
  `llm_refusals_total{category}`.
- The terminal gives every message its own request id: every line, the router's included.
- The mock: obeys text addressed to the assistant inside a tool result (injection, for the
  demonstration and the evals), declines on `[mock:refuse]`, plays the eval judge, and prices
  its tokens as `CHAT_MODEL`.
- The orchestrator reads the clock itself (`current_time`, `OWN_TOOLS` in `agent/team.py`):
  a small read-only tool is not worth a subagent.

### Changed
- `CHAT_WRITE_TOOLS=1` is refused when `APP_ENV=prod` (use `ask`).
- `list_notes` ignores a leading "the", "my", "our", "a" or "an" in its search ("the party"
  finds "party: ..."), found by an eval case.

## [0.19.0] - 2026-11-19

### Added
- A team of agents, off by default (`CHAT_TEAM=1`): a router (`agent/router.py`, structured
  output) sends a big review to an orchestrator (`agent/team.py`) whose only tool is
  `delegate`; two reading specialists (`notes`, `memory`) run as fresh agent loops with their
  own prompt, tools and context, and hand back a JSON report. Findings whose source no tool
  returned are marked unchecked.
- Independent delegations run at the same time (`CHAT_TEAM_PARALLEL`); a tool step runs in
  threads only when no call in it writes, and each thread keeps the request id.
- One budget per team run: `CHAT_TEAM_MAX_STEPS`, `CHAT_TEAM_MAX_TOKENS`, 120 seconds.
- `CHAT_WORKER_MODEL`: the router's and the specialists' model.
- Logs: an `agent` field (`orchestrator`, `orchestrator/notes`, ...); the terminal gets a
  request id per team run. Metrics: `agent_tokens_total{agent,kind}`, `team_runs_total`,
  `subagent_runs_total`, `routes_total`.
- `create()` on both clients takes a JSON schema for the final answer (tools and structured
  output in one request).
- The mock plays the router, the orchestrator and the specialists; `CHAT_MOCK_DELAY` makes
  every mock call wait, so time can be measured offline.
- `forget_memory`: the model can delete one of this client's memories, by its ref (a writing
  tool). The mock asks for it on `forget memory <ref>`.

### Changed
- Search over earlier conversations drops the s of a plural (`cakes` finds `cake`).

## [0.18.0] - 2026-11-19

### Added
- The context of every call is assembled within a budget (`agent/context.py`,
  `CHAT_CONTEXT_TOKENS`, default 16000 estimated tokens): the newest whole turns that fit, so
  a tool request is never sent without its result. `/context` shows where the tokens go.
- Compaction (`agent/compaction.py`, `CHAT_COMPACT`, on by default): when a turn would no
  longer fit, the older turns are summarised by the model, and the summary takes their place
  in the context. The turns stay stored. `/compact` summarises now. Metric
  `context_compactions_total`.
- Prompt caching in the real client: a cache breakpoint after the system prompt, and automatic
  caching of the whole prompt. Cache reads and writes are logged per step and counted in
  `llm_tokens_total{kind="cache_read"|"cache_write"}`. The mock plays the cache.
- `count_tokens` on both clients (the real one asks the API); `/context` prints it.
- Long-term memory per client (table `memories`): the tools `remember` (writes; long numbers
  refused), `recall` and `search_conversations` (keyword search over the client's earlier
  conversations). `/memories`, `/forget`; `GET /memories` and `DELETE /memories`.
- The mock: `keep in mind that ...`, `what do you remember about me`, `did we talk about ...`;
  scripted summaries; cache numbers.
- `current_time`: a read-only tool for today's date and time (`agent/clock.py`).
- The MCP server also offers a resource, `notes://conversation`: the conversation's notes, read
  through the same code as `list_notes`. `scripts/mcp_try.py read <uri>` reads it.
- `scripts/echo_server.py` answers `count_tokens` too.

### Changed
- The whole turn is stored: tool requests and results too (migration 0009, `messages.kind`),
  results cut to 1,000 characters. `GET /conversations/{id}` still shows text only.
- Every message goes through the agent loop, with or without a notes service (the clock and
  memory tools need no notes service). `CHAT_MAX_TURNS` is now an upper bound inside the
  token budget, and older turns are summarised rather than dropped.
- `llm_tokens_total{kind="input"}` counts only the part of the prompt the cache did not
  touch, as the API's `usage.input_tokens` does.

## [0.17.0] - 2026-11-19

### Added
- A tool registry (`agent/tools.py`): every tool is data (name, description, a Pydantic input
  model, the function, whether it writes). The input is validated before the tool runs; every
  failure is a result for the model that says how to recover. The loop has no tool code.
- Notes tools (`agent/notes_tools.py`): `list_notes` (search, at most 20 results, each note
  with an 8-character ref), `add_note` (the same note twice is saved once) and `delete_note`
  (only this conversation's notes). The writing tools only with `CHAT_WRITE_TOOLS=1`; every
  tool call is logged with `writes` and the conversation id.
- Several tool calls in one step; all their results go back in one message.
- `/title` in the chat: a title and a topic from the model as structured output, checked with
  Pydantic, one retry, then the automatic title (`agent/titles.py`).
- `python -m agent.mcp_server`: the notes tools as an MCP server over stdio, and
  `scripts/mcp_try.py`, a small MCP client. New dependency: `mcp`.
- The mock: `remember that ...`, `forget note <ref>`, several `[mock:call ...]` in one
  message, and `[mock:json {...}]` for structured output.

### Changed
- A wrong tool input now reads `Invalid input for <tool>: <field>: <problem>. Fix the input
  and call <tool> again.` (it was `Unknown input field(s): ...` or `search must be a string.`).

## [0.16.0] - 2026-11-19

### Added
- With a notes service, the model can read the conversation's notes: every message goes
  through a hand-written agent loop with one read-only tool, `list_notes` (`agent/loop.py`,
  `agent/tools.py`). At most `CHAT_MAX_STEPS` model calls per message (default 5). A failing
  tool becomes an error result for the model, not a failed request. Only the question and the
  final answer are saved.
- One log line per agent step and per tool call; metrics `agent_runs_total`, `agent_steps`,
  `agent_tool_calls_total`.
- `python -m agent.trace "<question>"` prints every message of one agent run.
- The mock can ask for tools: `[mock:call <tool> <json>]`, `[mock:loop]`, and any message
  that mentions `notes`.

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
