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

## Project layout

```
agent/
  __main__.py   entry point for `python -m agent`
  cli.py        the terminal chat loop
  config.py     settings from environment variables
  history.py    trimming the conversation
  llm.py        the real Claude client and the mock client
tests/          pytest tests; they run against the mock, never the real API
```

## Checks

Run all of these before you open a pull request. All of them must pass.

```powershell
uv run pytest            # tests
uv run ruff check        # lint
uv run ruff format       # format the code
uv run mypy agent        # type check
```
