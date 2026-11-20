# my-agent

A small chat agent that talks to Claude. Use it in the terminal, or run it as an HTTP
service with its own API and a web chat page.
It can also run in mock mode, which returns fake answers and needs no API key.

The repository holds two services (a monorepo): the chat service (`agent/`, this folder's
project) and the notes service (`notes-service/`, its own project). See `docs/architecture.md`.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python for you if needed)
- [Docker Desktop](https://docs.docker.com/desktop/), only to run the service with Postgres
  in containers (see "Run with Docker")

## Setup

```powershell
uv sync                    # build the virtual environment from uv.lock
cp .env.example .env       # create your private settings file
uv run alembic upgrade head  # create the database tables (see "The database")
```

Open `.env` and fill in the values (see the table below).

## Run in the terminal

```powershell
uv run python -m agent
```

Type a message and press Enter. The terminal chat writes its log to `agent.log` (JSON lines),
so the terminal stays clean for the conversation.

Every run starts a new conversation, titled by its first message: one line, at most 50
characters, cut after a whole word (`...` when cut).
`uv run python -m agent --continue` picks up the newest one.

## Run as an HTTP service

Set `AGENT_API_KEY` in `.env` first (the server refuses to start without it), then:

```powershell
uv run uvicorn agent.api:create_app --factory
```

The server listens on `http://127.0.0.1:8000` (only this computer). Stop it with Ctrl+C.

| Address | What is there |
|---|---|
| `http://127.0.0.1:8000/` | The web chat page. Paste your key in the key field; the page forgets it when the tab closes. |
| `http://127.0.0.1:8000/docs` | Swagger UI: every endpoint, try them in the browser (needs internet to load). |
| `http://127.0.0.1:8000/openapi.json` | The API description that Swagger is built from. |

| Endpoint | Key? | What it does |
|---|---|---|
| `GET /health` | no | Liveness: `{"status": "ok"}` whenever the process answers. |
| `GET /ready` | no | Readiness: 200 when the database answers, 503 when it does not; with the version and the environment. |
| `POST /chat` | yes | Send `{"message": "...", "conversation_id": "..."}`. Leave the id out to start a new conversation. Returns the reply, the id and the turn count. |
| `GET /conversations` | yes | The newest conversations (up to 50), newest first, with their titles. |
| `GET /conversations/{id}` | yes | The title and every message of that conversation, oldest first. |
| `DELETE /conversations/{id}` | yes | Delete the conversation, its messages and its notes (204), as a saga (see below). 503 when the notes service is unavailable: then nothing is deleted. |

Send the key in the `X-API-Key` header. From PowerShell:

```powershell
curl.exe http://127.0.0.1:8000/chat -H "Content-Type: application/json" -H "X-API-Key: <your key>" --data-binary "@examples/chat-hello.json"
uv run python scripts/ask.py "hello"
```

## The notes service

`notes-service/` is a second service: its own project (`pyproject.toml`, `uv.lock`, `.venv`),
its own database, its own image and its own version. The chat calls it over HTTP through
`agent/notes.py`, for `/note` and `/notes`. Its README says how to run and test it alone.

Without Docker, in two more terminals (set `NOTES_URL=http://127.0.0.1:8100` and the same
`NOTES_API_KEY` in `.env` first):

```powershell
cd notes-service
$env:NOTES_API_KEY = "<the NOTES_API_KEY from .env>"
uv run uvicorn notes.api:create_app --factory --port 8100
```

The notes client waits at most `NOTES_TIMEOUT` seconds per attempt, retries twice with
backoff and jitter, sends an `Idempotency-Key` with every new note (a retry never saves a
second copy), and stops calling for 30 seconds after 3 failed calls in a row (a circuit
breaker). If the notes service is down, the chat still answers; `/ready` shows
`"notes": "unreachable"` but stays 200.

## The agent loop and the notes tools

With a notes service (`NOTES_URL` set), every message goes through the agent loop
(`agent/loop.py`): the model may ask for tools, the program runs them and sends the results
back, and the model answers. Without a notes service there are no tools, and each message is
one model call.

The tools live in one registry (`agent/tools.py`); the notes tools are in
`agent/notes_tools.py`. Each tool is data: a name, a description written for the model, an
input model (Pydantic: its JSON schema is sent to the model, and the same class checks the
input before anything runs), the function, and whether it writes. The loop has no
tool-specific code.

| Tool | What it does | Writes |
|---|---|---|
| `list_notes` | Lists or searches (`search`) this conversation's notes, at most 20, as `- [ref] text` | no |
| `add_note` | Saves a note. The Idempotency-Key comes from the conversation and the text, so the same note twice is saved once | yes |
| `delete_note` | Deletes one note by its ref (8 characters from `list_notes`), only if it belongs to this conversation | yes |
| `current_time` | Today's date, weekday and time, in one of four time zones (`agent/clock.py`) | no |

The commands `/note` and `/notes` still work, with no model call (ADR 0003). `/note` makes a
new Idempotency-Key every time (twice: two notes); `add_note` one per conversation and text.

The conversation is chosen by the code, never by the model. Writing tools are offered only
with `CHAT_WRITE_TOOLS=1` (default off), and every tool call is logged with `"writes"` and the
conversation id. Human approval for risky tools is not built (a later chapter).
At most `CHAT_MAX_STEPS` model calls per message (default 5); then the loop stops and says
so. A failing tool (notes down, a wrong input, an unknown tool) becomes a result for the model,
with a message that says how to recover, never a crash. When the model asks for several tools
in one step, all their results go back in one message.

Only the question and the final answer are saved; the tool requests and results of a run are
not (`GET /conversations/{id}` shows text only).

Each step is one log line (`agent step N: <stop_reason>`, with tokens and Anthropic's request
id), each tool call one more (`tool <name>: ok|error`). Metrics: `agent_runs_total{stop}`,
`agent_steps` (model calls per run), `agent_tool_calls_total{tool,outcome}`.

To see every message of one run, as JSON (the tools work on the newest conversation):

```powershell
uv run python -m agent.trace "What did I save in my notes about milk?"
```

In mock mode the model is scripted (`MockClient.create` in `agent/llm.py`), on the user's last
message:

| In the message | The mock asks for |
|---|---|
| `[mock:call <tool> <json input>]` (one or more) | exactly those calls, in one step, offered or not |
| `remember that <text>` (one or more, each ends at `.`, `?`, `!`) | `add_note`, one call each, if offered |
| `forget note <ref>` | `delete_note`, if offered |
| the word `notes` (and nothing above) | `list_notes`, with `search` = the words after "about" |
| `what time`, `what day`, `what date` (and nothing above) | `current_time` |
| `[mock:loop]` | the same calls again after every result, until the step limit |

## A better title: structured output

`/title` in the chat asks the model for a title and a topic as JSON that must match a schema
(`agent/titles.py`, `TitleSuggestion`). The request uses the API's structured outputs
(`output_config.format`); the schema is made from the Pydantic class by the SDK's
`transform_schema`, which moves what the API cannot enforce (the 50-character limit) into the
description. Pydantic checks the answer. A rejected answer gets one retry with the reasons;
after that the automatic title stays. The topic is shown, not stored.

In mock mode, the answer is made-up values of the right type (`"mock title"`), or, for the
k-th attempt, the k-th different `[mock:json {...}]` found in the conversation.

## The notes tools over MCP

`agent/mcp_server.py` serves the same registry as an MCP server over stdio, so any MCP host
can use the notes tools. It works on one conversation (`--conversation ID`, default the newest)
and offers the writing tools only with `CHAT_WRITE_TOOLS=1` in `.env`. Its log goes to
`mcp.log`: stdout belongs to the protocol. Besides the tools, it offers one resource,
`notes://conversation` (the notes as text, for the host to read; `scripts/mcp_try.py read
notes://conversation`).

```powershell
uv run python scripts/mcp_try.py                          # start the server, list its tools
uv run python scripts/mcp_try.py list_notes search=milk    # and call one
```

A host application is configured with the command that starts the server: the project's
Python (`.venv\Scripts\python.exe`), the arguments `-m agent.mcp_server`, and this folder as
the working directory. The server reads `.env` itself; it does not see the host's variables.

## Run with Docker (the API and Postgres)

`compose.yaml` starts the containers below, and also Kafka, `topics` and the usage worker
(see "Events, Kafka and the usage worker"): `db` (Postgres 17, its data in the volume `pgdata`),
`migrate` (runs `alembic upgrade head` once, then exits), `api` (the HTTP service, started
only after the migrations succeeded), and the notes service: `notes` on
`http://127.0.0.1:8100` with its own Postgres, `notes-db` (volume `notesdata`). Compose reads
`NOTES_API_KEY` from `.env` for both services. To try failures, set
`$env:NOTES_DELAY_SECONDS = "3"` (or `$env:NOTES_FAIL_AFTER_SAVE = "1"`) and run
`docker compose up -d notes`; remove the variable and run it again to go back. The API reads `.env` for its settings, but its
`DATABASE_URL` comes from `compose.yaml` and points at Postgres.

```powershell
docker compose up --build -d --wait  # build the images, start everything, wait until healthy
docker compose ps -a             # db healthy, migrate exited (0), api up
docker compose logs api          # what the API printed
docker compose down              # stop and remove the containers; the data stays in the volume
docker compose down -v           # the same, and DELETE the volume: an empty database next time
```

The API is at `http://127.0.0.1:8000`, as before, so stop a local `uvicorn` first.
Postgres listens on `127.0.0.1:5432` for tools and scripts on this computer:
`docker compose exec db psql -U agent` opens its SQL shell.

Your SQLite file `agent.db` is not used by the containers and is not changed. To copy its
conversations into the (empty, migrated) Postgres database:

```powershell
uv run python scripts/copy_conversations.py sqlite:///agent.db postgresql+psycopg://agent:agent@127.0.0.1:5432/agent
```

After a change to the code, `docker compose up --build -d` rebuilds the image; only the
last layer (the code) is rebuilt unless `pyproject.toml` or `uv.lock` changed.

## Events, Kafka and the usage worker

When `KAFKA_BOOTSTRAP_SERVERS` is set (compose sets `kafka:9092`), the api publishes an event
to the topic `chat-events` after every reply (`message.created`) and after a deletion
(`conversation.deleted`). The key is the conversation id, so one conversation's events stay in
order. Without the variable nothing is published, and the tests and `uv run` need no Kafka.

The usage worker (`python -m worker`, the `worker` service) reads them in the consumer group
`usage-worker` and keeps turns and characters per conversation in its own SQLite file (volume
`usagedata`). It commits an offset only after the work is saved (at least once), and remembers
every event id it applied, so a repeated event changes nothing. A message it cannot read goes
to `chat-events-dlq`.

```powershell
docker compose exec worker python -m worker stats     # the statistics so far
docker compose logs worker                            # what it processed
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group usage-worker
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic chat-events --from-beginning
```

To rebuild the statistics from all the events: stop the worker, delete its file
(`docker compose run --rm --no-deps worker rm /data/usage.db`), reset the group
(`kafka-consumer-groups.sh ... --group usage-worker --reset-offsets --to-earliest --topic chat-events --execute`)
and start it again. Kafka keeps events for 7 days by default.

## Deleting a conversation: a saga

There is no transaction across the chat's database and the notes service, so
`DELETE /conversations/{id}` runs three local steps (`agent/saga.py`): archive the conversation
(hidden), delete its notes in the notes service, delete the conversation. If a step fails, the
steps already done are compensated, newest first: deleted notes are saved again (new ids), and
the conversation is un-archived. The api's log has one line per step and compensation, with
the request id.

## Logs, metrics and alerts

Every service writes its log to standard output, one JSON object per line, with a
`request_id`. The api takes it from an `X-Request-ID` header (when it looks like an id) or
makes one, sends it back in the answer, passes it to the notes service (`X-Request-ID`) and
into every Kafka event (header `request_id`), so the worker's lines carry it too.
`scripts/ask.py` prints it; the chat page shows it with an error.

```powershell
docker compose logs api notes worker --no-log-prefix | Select-String <request id>
docker compose logs api --no-log-prefix --since 10m | ForEach-Object { $_ | ConvertFrom-Json } | Format-Table time, level, message
```

Messages, notes and keys are never logged, only ids, counts and durations.

`GET /metrics` shows the api's metrics, but only with `Authorization: Bearer <METRICS_TOKEN>`
(unset: 404, no metrics). It shows in the Prometheus text format: requests by
route and status, latency histograms, model latency and tokens, notes calls and the circuit
breaker, events, sagas. The worker serves its own on port 9100 (events, dead letters, lag).
Prometheus scrapes both and evaluates `monitoring/alerts.yml`:

```powershell
docker compose --profile monitoring up -d      # Prometheus at http://127.0.0.1:9090 (needs METRICS_TOKEN in .env)
docker run --rm -v "${PWD}\monitoring:/m:ro" --entrypoint promtool prom/prometheus:v3.5.0 check config /m/prometheus.yml
```

`docs/runbook.md` says what to do for every alert; `docs/postmortem-template.md` is for after
an incident. `examples/incident/` holds the logs and metrics of one real incident (chapter 13).

## Security

`docs/security.md` is the threat model: what we protect, where requests come in, what each
part may do, and the known gaps. In short:

- **Keys per client.** Every client has its own key; the server keeps only its SHA-256
  (`AGENT_API_KEYS`, entries `name:hash`, comma separated). `uv run python scripts/new_key.py <name>`
  makes a key and prints its entry. `AGENT_API_KEY` still works: it is the client `default`,
  which also owns the terminal's conversations and every conversation from before 0.14.
- **Conversations belong to a client.** Another client's conversation answers 404, and
  `GET /conversations` lists only the caller's own.
- **Limits.** `/chat` allows `CHAT_RATE_LIMIT` messages per client per minute (default 30), then
  answers 429 with `Retry-After`. Request bodies over 64 KiB get 413. Conversation ids must be
  32 hex characters (422 otherwise).
- **Least privilege.** The images run as the user `app` (uid 10001), not root, and the image
  that runs has no uv in it (a two-stage build). Prometheus has its own token, which can read
  `/metrics` and nothing else.
- **Checks.** The CI job `security` scans the whole history for secrets (gitleaks) and the locked
  packages for known vulnerabilities (`uv audit`). On your computer:

```powershell
gitleaks git -v --redact .                        # every commit; install: see docs/security.md
uv audit --locked --preview-features audit        # the chat service's packages
cd notes-service; uv audit --locked --preview-features audit; cd ..
```

If a secret was ever committed: rotate it first (it is already copied), then clean the history.

After upgrading from 0.13 with Docker, the worker's volume still belongs to root (the worker
fails with `attempt to write a readonly database`). Fix it once:
`docker compose run --rm --no-deps --user root worker chown -R app /data`.

## Pipelines: the nightly usage report

`pipelines/usage_report.py` writes `reports/usage-<day>.csv`: turns and characters per
conversation on one day (UTC), from the messages table. Running a day again replaces its file.

```powershell
uv run python -m pipelines.usage_report                    # yesterday
uv run python -m pipelines.usage_report --day 2026-11-17   # any day (a backfill)
```

`dags/daily_usage_report.py` is an Airflow DAG that runs the same two functions every night
at 02:00 UTC for the day before. Airflow is not part of this project. To try the DAG once in a
throwaway container (it installs Airflow 3.4 there, which takes a few minutes), with the
compose `db` running:

```powershell
docker run --rm --network my-agent_default -v "${PWD}:/project:ro" python:3.13-slim bash /project/dags/try_in_docker.sh
```

## The database

Conversations and messages are stored in a database, so they survive a restart.
By default it is a SQLite file, `agent.db`, created in the folder you run from
(`DATABASE_URL` changes that). Look inside with Python's built-in SQLite shell:

```powershell
uv run python -m sqlite3 agent.db
```

Type SQL that ends with `;`, and `.quit` to leave.

### Migrations

The tables are created and changed only by migrations, with
[Alembic](https://alembic.sqlalchemy.org/). Every change to a table class in `agent/db.py`
needs a migration in `migrations/versions/`. The agent and the server refuse to start
when the database is behind the code.

```powershell
uv run alembic upgrade head        # bring the database up to date (also creates a new one)
uv run alembic current             # which revision the database is at
uv run alembic history             # every migration, newest first
uv run alembic downgrade -1        # undo the last migration (may delete data: back up first)
uv run alembic revision --autogenerate -m "what changes" --rev-id 0006   # a new migration
uv run alembic upgrade head --sql  # print the SQL instead of running it
```

`--sql` cannot print `0008`: it reads the conversations in Python (a data migration),
so it needs a database. It stops with an error that says so.

Back up before you migrate a database that holds data: stop the server, then
`Copy-Item agent.db agent-backup.db`. Always read a generated migration before you run it.
Migrations use the same `DATABASE_URL` as the agent (from the terminal or `.env`).

A database created before migrations (chapter 6) already has the tables of `0001`.
Do not upgrade it from nothing; mark it once with `uv run alembic stamp 0001`,
then `uv run alembic upgrade head`.

In `docker compose`, the `migrate` service runs `alembic upgrade head` before the API
starts; the API itself never migrates.

The tests do not run migrations for every test: an in-memory database gets its tables
straight from the classes (`create_all`). `tests/test_migrations.py` checks that the
migrations build exactly the same tables, and that every migration can be undone.
Those tests also run on Postgres when `TEST_DATABASE_URL` points at an empty database
(they delete every table in it):

```powershell
docker compose exec db createdb -U agent agent_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://agent:agent@127.0.0.1:5432/agent_test"
uv run pytest tests/test_migrations.py
Remove-Item Env:TEST_DATABASE_URL
```

## Commands inside the chat

| Command | What it does |
|---|---|
| `/reset` | Delete the messages of this conversation and start over. |
| `/history` | Show how many turns are saved in this conversation (the model sees the last `CHAT_MAX_TURNS`). |
| `/note <text>` | Save a note for this conversation, in the notes service. |
| `/notes` | List the notes of this conversation. |
| `/title` | Ask the model for a better title for this conversation (structured output). |
| `exit`, `quit`, `bye` | Leave the chat. |

## Environment variables

| Name | What it does | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your secret API key. Not needed in mock mode. | none |
| `CHAT_MODEL` | Which Claude model to chat with. | `claude-opus-5-5` |
| `CHAT_MOCK` | `1` = fake answers, free. `0` = real answers from the API. | `0` |
| `AGENT_NAME` | The name printed before each reply. | `agent` |
| `CHAT_MAX_TURNS` | How many recent turns are sent to the model. | `10` |
| `CHAT_MAX_STEPS` | Model calls for one message in the agent loop, at most (with a notes service). | `5` |
| `CHAT_WRITE_TOOLS` | `1` = the model may also add and delete notes (`add_note`, `delete_note`). | `0` |
| `CHAT_LOG_LEVEL` | How much is logged: `DEBUG`, `INFO`, `WARNING`, `ERROR`. Services log to stdout, the terminal chat to `agent.log`. | `INFO` |
| `ANTHROPIC_BASE_URL` | Where the SDK sends its requests. Set it to the echo server to see them. | the real API |
| `AGENT_API_KEY` | One key for this agent's own API (`X-API-Key`): the client `default`. The server needs it or `AGENT_API_KEYS`. `ask.py` sends it. | none |
| `AGENT_API_KEYS` | More clients: `name:sha256-of-key` entries, comma separated (`scripts/new_key.py`). | none |
| `CHAT_RATE_LIMIT` | `/chat` messages per client per minute; more get 429. | `30` |
| `METRICS_TOKEN` | The token that may read `/metrics` (Prometheus sends it). Unset: no `/metrics`. | none |
| `AGENT_URL` | Where `scripts/ask.py` finds the API. | `http://127.0.0.1:8000` |
| `DATABASE_URL` | Which database stores the conversations (a SQLAlchemy URL). In `docker compose`, set by `compose.yaml` to Postgres. | `sqlite:///agent.db` |
| `DATABASE_PASSWORD` | The database password, when it is not inside `DATABASE_URL` (deployed environments keep it apart, as a secret). | none |
| `APP_ENV` | Where the agent runs: `local`, `staging` or `prod`. Outside `local`, `DATABASE_URL` is required. | `local` |
| `NOTES_URL` | Where the notes service is. Unset: no notes (`/note` says so) and no tools. | none |
| `NOTES_API_KEY` | The key the notes service expects (`X-API-Key`). The notes service reads the same name. | none |
| `NOTES_TIMEOUT` | Seconds to wait for the notes service, per attempt (there are up to 3). | `2` |
| `KAFKA_BOOTSTRAP_SERVERS` | Where Kafka is. Set: the api publishes events, and the worker can run. | none |
| `WORKER_GROUP` | The worker's consumer group. | `usage-worker` |
| `USAGE_DATABASE_URL` | The worker's own database (statistics). | `sqlite:///usage.db` |
| `WORKER_METRICS_PORT` | Where the worker serves its `/metrics`. | `9100` |
| `TEST_DATABASE_URL` | An empty Postgres database for the migration tests. Unset: those tests run on SQLite only. | none |

`ANTHROPIC_API_KEY`, `AGENT_API_KEY`, `AGENT_API_KEYS`, `METRICS_TOKEN`, `NOTES_API_KEY` and `DATABASE_PASSWORD` can also come from a file:
set `<NAME>_FILE` to its path (for example `AGENT_API_KEY_FILE=/run/secrets/agent_api_key`).
The file wins over the variable. This is how the deployed environments get their secrets.

## Project layout

```
agent/
  __main__.py   entry point for `python -m agent`
  api.py        the HTTP API (FastAPI): schemas, endpoints, API-key check
  cli.py        the terminal chat loop
  conversations.py  the core: conversations by id, saved in the database; used by the CLI and the API
  db.py         the tables (SQLAlchemy); make_engine() connects and checks the migrations
  config.py     settings from environment variables
  history.py    trimming the conversation
  llm.py        the real Claude client and the mock client (reply: one call; create: one agent
                step; reply_json: JSON that matches a schema)
  loop.py       the agent loop: call, run the tools it asks for, send results, until done or max steps
  tools.py      the tool registry: Tool, ToolRegistry, Toolbox (validation, errors, logging)
  notes_tools.py  the notes tools: list_notes, add_note, delete_note
  titles.py     /title: a title as structured output, checked with Pydantic
  mcp_server.py `python -m agent.mcp_server`: the notes tools as an MCP server (stdio)
  trace.py      `python -m agent.trace "..."`: print every message of one agent run
  notes.py      the notes service's client (timeouts, retries, idempotency, breaker) and /note
  events.py     publishing events to Kafka
  saga.py       the saga runner, and the steps that delete a conversation
  logs.py       JSON log lines and the request id
  metrics.py    the metrics (Prometheus client), served at /metrics
  security.py   keys per client (hashed), the rate limiter
worker/         the usage worker: usage.py (tables, apply an event), __main__.py (the Kafka loop)
pipelines/      batch jobs: usage_report.py (the nightly report)
dags/           Airflow: daily_usage_report.py, and try_in_docker.sh to run it once
  static/chat.html  the web chat page (right-to-left, no build step, works offline)
migrations/     Alembic: env.py (which database) and versions/ (one file per change)
alembic.ini     Alembic settings (the database URL comes from DATABASE_URL, not from here)
Dockerfile      how the image of the API is built
.dockerignore   what never goes into the image (.env, databases, .venv, .git, tests)
compose.yaml    both services and their databases, started together (local development)
notes-service/  the notes service: its own project, Dockerfile, tests and README
docs/           architecture.md, security.md (threat model), runbook.md (one entry per alert),
                postmortem-template.md, postmortems/, design/ (design docs), adr/ (decisions)
monitoring/     prometheus.yml (what to scrape) and alerts.yml (the alert rules)
deploy/         the staging and prod environments: compose.yaml, one .env per environment,
                and secrets/ (created by scripts/make_secrets.py, never in git or the image)
examples/       request bodies for curl.exe; incident/: evidence of a real incident, to diagnose;
                team/: a ticket and a pull request description, as examples
scripts/        small tools for learning and debugging (see below)
tests/          pytest tests; they run against the mock, never the real API
.github/workflows/  on GitHub: ci.yml runs on every pull request, release.yml on a version tag
CHANGELOG.md    what changed in every release
.python-version the one Python version of the project (uv, CI and the Dockerfile)
```

## Scripts

Each one runs on your own computer only. Stop a server with Ctrl+C.
The echo server and the agent's API both use port 8000: run one at a time.

| Script | What it does |
|---|---|
| `uv run python scripts/raw_http.py 127.0.0.1 8000` | Sends one HTTP request by hand, as plain text, and prints the reply. |
| `uv run python scripts/echo_server.py` | A server on `127.0.0.1:8000` that prints every request it gets. `POST /v1/messages` gets a fake Claude reply. `--status 529` makes it answer every request with that status instead. |
| `uv run python scripts/probe.py <url>` | Checks a URL step by step (DNS, connect, HTTP) and says where it fails. |
| `uv run python scripts/ask.py "hello" [--conversation ID]` | A small client of the agent's own API: sends one message to `POST /chat`. |
| `uv run python scripts/copy_conversations.py <from> <to>` | Copies every conversation from one database into another, empty one (for example SQLite to Postgres). |
| `uv run python scripts/make_secrets.py staging` | Creates the missing secrets of an environment in `deploy/secrets/` (see "Deploy"). |
| `uv run python scripts/deploy.py staging` | Deploys an environment on this computer and checks it (see "Deploy"). |
| `uv run --locked python scripts/ci_local.py` | Runs the commands of the CI workflow on this computer, in the same order (see "Checks and CI"). |
| `uv run python scripts/index_lab.py` | Times one query on 500,000 messages, without and with an index (in memory, no file). |
| `uv run python scripts/new_key.py <name>` | Makes an API key for one client, and the `name:hash` entry for `AGENT_API_KEYS`. |
| `uv run python scripts/injection_lab.py "<name>"` | SQL injection, harmlessly: one search written unsafely and safely, on a table in memory. |
| `uv run python scripts/mcp_try.py [tool key=value ...]` | Starts the notes MCP server, lists its tools, and calls one (an MCP client, no host needed). |

To see what the agent really sends, start the echo server, then in a second terminal:

```powershell
$env:CHAT_MOCK = "0"
$env:ANTHROPIC_API_KEY = "not-a-real-key"
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:8000"
uv run python -m agent
```

Use `127.0.0.1`, not `localhost`: on Windows, `localhost` tries IPv6 (`::1`) first, and the
echo server listens only on IPv4, so every request waits about two seconds.

## Checks and CI

The project runs on one Python version, written once in `.python-version` (3.13).
uv reads it on your computer and in CI; `tests/test_python_version.py` fails if the
`Dockerfile` starts from a different one.

Every pull request, and every push to `main`, runs `.github/workflows/ci.yml` on GitHub:

| Job | What it runs |
|---|---|
| `Lint, types and tests` | `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy agent scripts worker pipelines`, `pytest` (the migration tests also run on a Postgres service container) |
| `Notes service` | the same checks, inside `notes-service/` (`mypy notes`) |
| `Build the images` | `docker build` of both images, then starts each app once inside its image |
| `Secrets and known vulnerabilities` | gitleaks over every commit; `uv audit --locked` in both projects |

Every action is pinned to a commit SHA (the tag is in a comment): a tag can be moved to other
code, a commit cannot. To update an action, look up the new tag's commit
(`git ls-remote --tags https://github.com/<owner>/<action>.git`) and change both.

Run the same commands on your computer, in the same order, before you push:

```powershell
docker compose up -d db                                  # Postgres for the migration tests
docker compose exec db createdb -U agent agent_test      # once; "already exists" is fine
uv run --locked python scripts/ci_local.py               # every job; it stops at the first failure
uv run --locked python scripts/ci_local.py --job checks  # one job
```

`--locked` makes uv refuse to change `uv.lock`, as in CI. Without Postgres, the migration
tests fail with a connection error: start `db` first. `uv run pytest` alone skips them
(`TEST_DATABASE_URL` is not set there). `uv run ruff format` (without `--check`) fixes the formatting.

After you change a workflow file, check it:
`uvx --from actionlint-py actionlint` (it reads every file in `.github/workflows`).

## Deploy: staging and prod on this computer

`deploy/` describes two deployed environments that run side by side, each with its own
databases, its own secrets and its own port: staging on `http://127.0.0.1:8001`, prod on
`http://127.0.0.1:8002`. Both run the same image, `my-agent:<version>`; the settings come
from `deploy/staging.env` and `deploy/prod.env` (in git, no secrets). The version that runs
is `IMAGE_TAG` in that file, so `git log deploy/` is the history of what ran where.

Once per environment, create its secrets (files in `deploy/secrets/<environment>/`). The api
gets only `api_clients.txt` (key hashes); `deploy_key.txt`, the plain key `deploy.py` uses for its
smoke test, never leaves this computer. (`agent_api_key.txt` from before 0.14 is no longer used:
delete it.)

```powershell
uv run python scripts/make_secrets.py staging
uv run python scripts/make_secrets.py prod
```

Each environment also runs the notes service, `my-agent-notes:<NOTES_IMAGE_TAG>`, with its own
Postgres and no port on this computer (only the api reaches it). The two services have
separate versions: changing only `NOTES_IMAGE_TAG` deploys only the notes service.

To deploy a version: build its image, set `IMAGE_TAG` in the environment's file, commit, deploy.
Always staging first; prod only after staging was checked.

```powershell
docker build -t my-agent:0.11.0 .
docker build -t my-agent-notes:0.1.0 notes-service
uv run python scripts/deploy.py staging   # migrations, start, wait until healthy, /ready, a smoke test
uv run python scripts/deploy.py prod
```

`deploy.py` stops at the first step that fails; it also fails when `/ready` does not report
`"notes": "ok"`. See what runs with
`docker compose -p my-agent-staging -f deploy/compose.yaml --env-file deploy/staging.env ps`
(the same with `logs api`, `stop db`, `down`).

### Rolling back

Set `IMAGE_TAG` back to the previous version (`git revert` the deploy commit), then:

```powershell
uv run python scripts/deploy.py staging --skip-migrations
```

Never run the migrations of an older image: it does not know the newer revisions, and the
database stays as the newer version left it. That is why every migration must be safe for
the previous version (expand first, contract only in a later release).

### Rotating a secret

Delete its file, run `make_secrets.py` again (it also rewrites `api_clients.txt`), then recreate
the containers that read it:
`docker compose ... up -d --force-recreate api`. The database password cannot be changed
this way: Postgres reads it only when the volume is created.

## Releases

The version is written once, in `pyproject.toml` (the API reports it in `/openapi.json`).
Pushing a tag `vX.Y.Z` to GitHub runs `.github/workflows/release.yml`: it checks the tag
against `pyproject.toml` and `CHANGELOG.md` (`scripts/release_notes.py`), builds the image
`ghcr.io/<owner>/<repo>:X.Y.Z`, pushes it, and creates a GitHub release. The steps for a
release are in CONTRIBUTING.md.
