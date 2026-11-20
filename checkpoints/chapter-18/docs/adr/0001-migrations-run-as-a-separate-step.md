# ADR 0001: Migrations run as a separate step

Status: accepted (chapter 7, written down in chapter 15). Date: 2026-11-19.

## Context

The tables change over time (`migrations/versions/`). Something must run `alembic upgrade
head` before new code uses a new column. The simplest place is the app itself, at startup.
But the api can run as several copies, a migration can fail half way, and some migrations
take long or must not run at all during a rollback.

## Decision

Migrations run only as their own step: `alembic upgrade head` by hand, the `migrate` service
in `compose.yaml`, and step 1 of `scripts/deploy.py`. The app never migrates. At startup it
checks the database (`check_schema` in `agent/db.py`): behind the code, it refuses to start;
ahead of the code (a rollback), it logs a warning and runs.

## Consequences

- One process migrates, once, and its output is read before the app starts.
- A failed migration stops the deploy before any new code serves users.
- A rollback runs old code on the new schema (`--skip-migrations`), so every migration must
  work with the version before it: expand first, contract in a later release.
- One more step to remember on a new machine (`alembic upgrade head`, in the README setup).
- Data migrations that need Python (like `0008`) cannot be printed with `--sql`.

## Alternatives considered

- Migrate at app startup: every copy races to migrate, and a slow migration delays health
  checks until the platform restarts the app in the middle of it.
- `create_all` (chapter 6): creates missing tables, never changes existing ones.
