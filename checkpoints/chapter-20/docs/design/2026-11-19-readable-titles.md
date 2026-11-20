# Design: readable conversation titles

Ticket: AGENT-42. Author: Reader. Status: accepted. Date: 2026-11-19.

## Problem

A conversation's title is `text[:50]` of its first message. Clients that list conversations
(`GET /conversations`, the terminal's `--continue`) show titles cut in the middle of a word,
with line breaks from pasted text, and with no sign that they were cut. Every client would
have to clean them up on its own.

## Goals

- Titles that fit on one line: whitespace collapsed, at most 50 characters.
- Cut at a word boundary, with `...` when something was cut.
- The same for conversations that already exist.

## Non-goals

- Renaming conversations, titles written by the model, a different length.
- Any change to the API's shape.

## Options considered

| Option | For | Against |
|---|---|---|
| A. Each client cleans the title | No server change | Every client repeats the work, and the stored title is already cut at 50: a client cannot find the last whole word |
| B. Compute the title when reading, from the first message | Old conversations fixed with no migration | One more query per listed conversation (50 per list), on every read, forever |
| C. Compute a clean title when the first message is saved, and fix old rows once in a migration | One cheap rule, written once; reads stay as they are | A data migration on a table that grows |

## Decision

Option C. `make_title(text)` in `agent/conversations.py` builds the title; `send()` uses it.
Migration `0008` rewrites the titles of existing conversations whose title is still the
automatic one, `first_message[:50]`. It has its own copy of the rule: a migration must keep
doing what it did, even after the code in `agent/` changes.

`...` is three ASCII dots, not the single character `…`: titles are printed in terminals and
written to files, where the single character can fail in some Windows code pages.

## Risks

- **A large table.** The migration reads every conversation with its first message, in
  Python. Fine at our size (hundreds of rows); for millions it would need batches.
- **Conversations that were reset** (`/reset` deletes the messages, not the title) have a
  title that no longer matches their first message: the migration leaves them unchanged.
- **During a deploy**, migrate runs before the new api starts; a conversation started in
  between gets an old-style title. Rare, harmless, and not worth a second migration.
- **Old code on the new data** (a rollback): no column changed, so 0.14.0 keeps working; the
  titles stay clean. `check_schema` logs that the database is newer than the code.

## Rollout and rollback

Ordinary release: CI green, merge, version, staging, prod (CONTRIBUTING.md, "Deploying").
Rollback: revert the deploy commit and deploy with `--skip-migrations`. `alembic downgrade`
restores the old titles, but like every downgrade it is for development databases, not prod.

## Open questions

- Should titles also drop Markdown (`**`, `#`) that the user pasted? Not now; wait for a report.
- Should the page get a conversation list? A separate ticket.

## Estimate

Before starting (hours, as ranges; the unknown first), and what happened:

| Task | Estimate | What happened |
|---|---|---|
| Clarify the ticket, reproduce it | 0.5 | As planned |
| This design doc | 0.5 to 1 | As planned |
| Spike: a data migration with Python logic, on a copy of agent.db | 0.5 to 1.5 | Found that `--sql` cannot run it: a clear error, and a README line |
| `make_title` and its tests | 1 to 1.5 | One older test expected the old title; updated |
| Migration 0008 and its test, SQLite and Postgres | 1 to 2 | The test of 0002 upgraded to head, so 0008 broke it: pinned to its revision (0007's too, found in self-review) |
| Docs, changelog, PR description, self-review | 1 | Longer: the definition of done and the PR template did not exist yet |
| Review and merge | 0.5 | |
| **Total** | **5 to 8** | Both surprises came in the two tasks with the widest ranges: the unknowns |
