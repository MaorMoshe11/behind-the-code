# Checkpoints

Each folder holds the whole project exactly as it should look after finishing that chapter
and all of its exercises. Use them to compare with your own project when something does not
match, or to start a chapter from a known state.

`chapter-NN` is the starting point of chapter NN+1. `chapter-17` is identical to
`chapter-16`, because chapter 17 does not change the project. `chapter-21` is the finished
project, released as version 1.0.0, and its `README.md` describes all of it.

## Using a checkpoint

Copy the folder out of this repository before you run it, to a place that is not synced by
OneDrive or a similar tool:

```powershell
cp -Recurse checkpoints\chapter-07 ~\projects\my-agent-ch07
cd ~\projects\my-agent-ch07
uv sync
```

Then follow the `README.md` inside it. From chapter 3 on, `uv run pytest` runs the tests.
Everything runs in mock mode (`CHAT_MOCK=1`) with no API key.

A checkpoint never contains `.venv`, `.env`, databases or git history: you create those
yourself, as the chapters explain.

## What each one adds

| Checkpoint | The project at that point |
|---|---|
| 01 | `chat.py`, a `uv` project, `.env.example`, mock mode |
| 02 | The same under git, with a `/reset` command and `CONTRIBUTING.md` |
| 03 | An `agent/` package with tests, linting, type hints and logging |
| 04 | Scripts that send raw HTTP and a tiny local server |
| 05 | A FastAPI service: `POST /chat`, `GET /health`, an API key, a web chat page |
| 06 | Conversations stored in a database through SQLAlchemy |
| 07 | Alembic migrations |
| 08 | A Dockerfile and Docker Compose with Postgres |
| 09 | GitHub Actions workflows, a changelog, a local CI script |
| 10 | Staging and prod as configuration, a deploy script, readiness checks |
| 11 | A second service (`notes-service/`) and a resilient client for it |
| 12 | Kafka events and a worker, a delete saga, an Airflow DAG |
| 13 | JSON logs with request ids, metrics, alert rules, saved incident evidence |
| 14 | Per-client keys, ownership of conversations, rate limiting, security checks in CI |
| 15 | A ticket carried to a merged change, with its design doc and PR description |
| 16 | The agent loop with one tool |
| 17 | Unchanged |
| 18 | A tool registry, notes tools, structured output, an MCP server |
| 19 | Context budget, compaction, prompt caching, search and long-term memory |
| 20 | A router, an orchestrator and specialist subagents |
| 21 | Evals, traces, cost, guardrails and human approval: version 1.0.0 |
