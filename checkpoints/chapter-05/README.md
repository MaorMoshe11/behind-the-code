# my-agent

A small chat agent that talks to Claude. Use it in the terminal, or run it as an HTTP
service with its own API and a web chat page.
It can also run in mock mode, which returns fake answers and needs no API key.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python for you if needed)

## Setup

```powershell
uv sync                  # build the virtual environment from uv.lock
cp .env.example .env     # create your private settings file
```

Open `.env` and fill in the values (see the table below).

## Run in the terminal

```powershell
uv run python -m agent
```

Type a message and press Enter. The agent writes a log to `agent.log`.

## Run as an HTTP service

Set `AGENT_API_KEY` in `.env` first (the server refuses to start without it), then:

```powershell
uv run uvicorn agent.api:create_app --factory
```

The server listens on `http://127.0.0.1:8000` (only this computer). Stop it with Ctrl+C.

| Address | What is there |
|---|---|
| `http://127.0.0.1:8000/` | The web chat page. Paste your `AGENT_API_KEY` in the key field once. |
| `http://127.0.0.1:8000/docs` | Swagger UI: every endpoint, try them in the browser (needs internet to load). |
| `http://127.0.0.1:8000/openapi.json` | The API description that Swagger is built from. |

| Endpoint | Key? | What it does |
|---|---|---|
| `GET /health` | no | `{"status": "ok"}` when the service is up. |
| `POST /chat` | yes | Send `{"message": "...", "conversation_id": "..."}`. Leave the id out to start a new conversation. Returns the reply, the id and the turn count. |
| `GET /conversations/{id}` | yes | The messages the agent remembers in that conversation. |
| `DELETE /conversations/{id}` | yes | Forget the conversation (204). |

Send the key in the `X-API-Key` header. From PowerShell:

```powershell
curl.exe http://127.0.0.1:8000/chat -H "Content-Type: application/json" -H "X-API-Key: <your key>" --data-binary "@examples/chat-hello.json"
uv run python scripts/ask.py "hello"
```

Conversations are kept in memory only: restarting the server forgets all of them.

## Commands inside the chat

| Command | What it does |
|---|---|
| `/reset` | Forget the conversation and start a new one. |
| `/history` | Show how many turns the agent remembers (at most `CHAT_MAX_TURNS`). |
| `exit`, `quit`, `bye` | Leave the chat. |

## Environment variables

| Name | What it does | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your secret API key. Not needed in mock mode. | none |
| `CHAT_MODEL` | Which Claude model to chat with. | `claude-opus-5-5` |
| `CHAT_MOCK` | `1` = fake answers, free. `0` = real answers from the API. | `0` |
| `AGENT_NAME` | The name printed before each reply. | `agent` |
| `CHAT_MAX_TURNS` | How many recent turns are sent to the model. | `10` |
| `CHAT_LOG_LEVEL` | How much goes into `agent.log`: `DEBUG`, `INFO`, `WARNING`, `ERROR`. | `INFO` |
| `ANTHROPIC_BASE_URL` | Where the SDK sends its requests. Set it to the echo server to see them. | the real API |
| `AGENT_API_KEY` | The key clients must send to this agent's own API (`X-API-Key`). Required by the server. | none |
| `AGENT_URL` | Where `scripts/ask.py` finds the API. | `http://127.0.0.1:8000` |

## Project layout

```
agent/
  __main__.py   entry point for `python -m agent`
  api.py        the HTTP API (FastAPI): schemas, endpoints, API-key check
  cli.py        the terminal chat loop
  conversations.py  the core: conversations by id, used by both the CLI and the API
  config.py     settings from environment variables
  history.py    trimming the conversation
  llm.py        the real Claude client and the mock client
  static/chat.html  the web chat page (right-to-left, no build step, works offline)
examples/       request bodies for curl.exe
scripts/        small network tools for learning and debugging (see below)
tests/          pytest tests; they run against the mock, never the real API
```

## Network scripts

Each one runs on your own computer only. Stop a server with Ctrl+C.
The echo server and the agent's API both use port 8000: run one at a time.

| Script | What it does |
|---|---|
| `uv run python scripts/raw_http.py 127.0.0.1 8000` | Sends one HTTP request by hand, as plain text, and prints the reply. |
| `uv run python scripts/echo_server.py` | A server on `127.0.0.1:8000` that prints every request it gets. `POST /v1/messages` gets a fake Claude reply. `--status 529` makes it answer every request with that status instead. |
| `uv run python scripts/probe.py <url>` | Checks a URL step by step (DNS, connect, HTTP) and says where it fails. |
| `uv run python scripts/ask.py "hello" [--conversation ID]` | A small client of the agent's own API: sends one message to `POST /chat`. |

To see what the agent really sends, start the echo server, then in a second terminal:

```powershell
$env:CHAT_MOCK = "0"
$env:ANTHROPIC_API_KEY = "not-a-real-key"
$env:ANTHROPIC_BASE_URL = "http://127.0.0.1:8000"
uv run python -m agent
```

Use `127.0.0.1`, not `localhost`: on Windows, `localhost` tries IPv6 (`::1`) first, and the
echo server listens only on IPv4, so every request waits about two seconds.

## Checks

Run all of these before you open a pull request. All of them must pass.

```powershell
uv run pytest            # tests
uv run ruff check        # lint
uv run ruff format       # format the code
uv run mypy agent scripts  # type check
```
