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
uv run python chat.py
```

Type a message and press Enter. Type `exit` to quit.

## Environment variables

| Name | What it does | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your secret API key. Not needed in mock mode. | none |
| `CHAT_MODEL` | Which Claude model to chat with. | `claude-opus-5-5` |
| `CHAT_MOCK` | `1` = fake answers, free. `0` = real answers from the API. | `0` |
| `AGENT_NAME` | The name printed before each reply. | `agent` |
