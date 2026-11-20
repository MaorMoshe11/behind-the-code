## What
Conversation titles are one line, at most 50 characters, cut after a whole word, with `...`
when something was cut. Migration `0008` gives existing conversations the same titles.

Before: `Here is my error:\nTraceback (most recent call last`
After:  `Here is my error: Traceback (most recent call...`

## Why
Ticket: AGENT-42 (Dana's sidebar shows titles cut mid-word, with line breaks).
Design: `docs/design/2026-11-19-readable-titles.md` (why the server, why a migration).

## How to test
1. `uv run pytest tests/test_titles.py tests/test_migrations.py`: one case per acceptance
   criterion; with `TEST_DATABASE_URL`, the migration runs on Postgres too.
2. On a copy of a real database:
   `Copy-Item agent.db try.db; $env:DATABASE_URL = "sqlite:///try.db"; uv run alembic upgrade head`,
   then `uv run python -m sqlite3 try.db "SELECT title FROM conversations"`.
   `uv run alembic downgrade 0007` puts the old titles back.

## Definition of done
- [x] Acceptance criteria checked: 1 to 7 by tests, 8 by `tests/test_api.py` (unchanged, green)
- [x] Tests, and `ci_local.py` green (with Postgres)
- [x] Migration works with the previous version (no column changes; 0.14.0 runs on it), and has a downgrade
- [x] Settings, logs, metrics, security: nothing new
- [x] README, docs/ and CHANGELOG "Unreleased" updated
- [x] Can be rolled back: revert and deploy with `--skip-migrations`; titles stay clean

## Notes for the reviewer
- The migration has its own copy of `make_title` on purpose (see its docstring).
- It cannot run with `--sql`, and says so: it reads the conversations in Python.
- Two old migration tests upgraded to `head`; they now stop at their own revision.
- Also adds the definition of done to CONTRIBUTING.md and a pull request template.
