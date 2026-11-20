# my-agent

A small chat agent that runs in the terminal and talks to Claude.
It can also run in mock mode, which returns fake answers and needs no API key.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python for you if needed)

## Setup

```powershell
uv sync                  # build the virtual environment from uv.lock
cp .env.example .env     # create your private settings file
```

Open `.env` and fill in the values (see the table below).

## Run

```powershell
uv run python -m agent
```

Type a message and press Enter. The agent writes a log to `agent.log`.

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

## Project layout

```
agent/
  __main__.py   entry point for `python -m agent`
  cli.py        the terminal chat loop
  config.py     settings from environment variables
  history.py    trimming the conversation
  llm.py        the real Claude client and the mock client
scripts/        small network tools for learning and debugging (see below)
tests/          pytest tests; they run against the mock, never the real API
```

## Network scripts

Each one runs on your own computer only. Stop a server with Ctrl+C.

| Script | What it does |
|---|---|
| `uv run python scripts/raw_http.py 127.0.0.1 8000` | Sends one HTTP request by hand, as plain text, and prints the reply. |
| `uv run python scripts/echo_server.py` | A server on `127.0.0.1:8000` that prints every request it gets. `POST /v1/messages` gets a fake Claude reply. `--status 529` makes it answer every request with that status instead. |
| `uv run python scripts/probe.py <url>` | Checks a URL step by step (DNS, connect, HTTP) and says where it fails. |

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
