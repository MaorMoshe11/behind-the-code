# Design: deleting old conversations

Ticket: AGENT-43. Author: Reader. Status: proposed (chapter 15, exercise 6). Date: 2026-11-20.

## Problem

Conversations are kept until someone deletes them (`docs/security.md`, gap 7). Messages and
notes are personal data, kept only to show a conversation again. We need a period after
which they are deleted, everywhere they live.

## Goals

- Delete every conversation whose last message is older than `CHAT_RETENTION_DAYS` (90),
  with its notes, once a night.
- Finish conversations that a failed delete saga left archived (`docs/architecture.md`).
- Every run says what it did: counts in a log line and in a metric.

## Non-goals

- Backups, a period per client, telling the users (separate tickets).

## Options considered

| Option | For | Against |
|---|---|---|
| A. A command in the chat image, `python -m agent.retention`, run nightly by a scheduler | Reuses the delete saga and the notes client; one run at a time; easy to run by hand with `--dry-run` | Needs a scheduler outside the app |
| B. An Airflow DAG (chapter 12) | A scheduler with retries and history | `pipelines/` must not import `agent`, but deleting needs the saga; a second way to delete |
| C. A loop inside the api | No new process | Runs once per api copy; ties deleting data to serving users |
| D. In the usage worker | A process that is always on | The worker reacts to events; it has no clock and no notes client |

## Decision

Option A. `agent/retention.py` finds the ids (one query: conversations whose newest message,
or creation time when there is none, is older than the cutoff; plus archived ones older than
an hour), then calls `delete_conversation` for each, at most `--limit` (500) per run. A
failure is logged and counted, and the run goes on. `--dry-run` prints the counts and
deletes nothing. In compose, a `retention` service under a profile, started each night by
the host's scheduler (Windows Task Scheduler here, a scheduled job in a cloud).

## Risks

- **Deleting the wrong conversations.** The query is the risky part: tested at the edges
  (exactly 90 days, no messages, archived), first released with the schedule running
  `--dry-run` only, for a week, in staging and prod. Deleted data cannot come back.
- **Many notes calls** on the first real run (every conversation older than 90 days at once):
  the limit spreads them over nights; the circuit breaker stops a run against a sick notes
  service.
- **Speed.** "Newest message per conversation" is a GROUP BY over messages; fine now, an
  index on `messages.created_at` later if the run gets slow.
- **Clocks.** `created_at` holds naive UTC values: the cutoff must be naive UTC too.

## Rollout and rollback

Four pull requests: (1) the query and `--dry-run`, with tests; (2) deleting through the saga,
the log line and the metric; (3) the compose service, the schedule, the runbook entry and
`docs/security.md`; (4) finishing archived conversations. Release after (3) with the schedule
in dry-run; switch it to real deletes in a later deploy commit. Rollback: stop the schedule.

## Open questions

- Is 90 days right? Ask whoever answers for the users' data (and, for a real service, a lawyer).
- Should a client be able to ask for a shorter period?
- Backups keep everything: how long, and how are deletions applied to them?

## Estimate

| Task | Estimate (hours) | Unknown? |
|---|---|---|
| Spike: the query on Postgres and SQLite, with naive UTC times | 1 to 2 | yes: do it first |
| PR 1: query, `--dry-run`, tests | 2 to 3 | |
| PR 2: delete through the saga, log, metric, tests | 2 to 4 | the saga with many ids |
| PR 3: compose service, schedule, runbook, security.md | 2 to 4 | the scheduler on Windows |
| PR 4: archived conversations | 1 to 2 | |
| Review rounds | 2 to 3 | |
| **Total** | **10 to 18** (two to three days) | |
