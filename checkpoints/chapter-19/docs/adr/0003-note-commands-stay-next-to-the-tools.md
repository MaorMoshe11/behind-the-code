# ADR 0003: /note and /notes stay, next to the notes tools; writing tools stay off by default

Status: accepted (chapter 18). Date: 2026-11-19.

## Context

Since 0.17.0 the model can save, list and delete notes through tools (`add_note`,
`list_notes`, `delete_note`). The commands `/note <text>` and `/notes` from chapter 11 do the
same without the model. Keep both, or let the tools replace the commands?

Measured in mock mode, one message each, a fake notes service, the project's own metrics
(`agent_steps`, `llm_tokens_total`). The tokens are the mock's made-up count, so only the
comparison means something:

| Message | `CHAT_WRITE_TOOLS` | Model calls | Notes calls | Tokens | Saved? |
|---|---|---|---|---|---|
| `/note buy stamps` | 0 or 1 | 0 | 1 (POST) | 0 | yes |
| "Remember that I need to buy stamps." | 0 | 1 | 0 | 302 | no: the model has no writing tool |
| "Remember that I need to buy stamps." | 1 | 2 | 1 (POST) | 1,164 | yes |

## Decision

Keep `/note` and `/notes`. The tools are for what people write in their own words; the
commands are the exact, free and predictable way. Keep `CHAT_WRITE_TOOLS` off by default:
reading tools for everyone, writing tools for whoever turns them on.

## Consequences

- Two ways to save a note. The commands make a new Idempotency-Key per command (a person who
  sends `/note` twice gets two notes); the tool uses one key per conversation and text (the
  same note twice is saved once). The difference is written in the README.
- A note saved by a command is listed by the tool, and the other way round: one service, one
  conversation id.
- With writing tools off, "remember that ..." gets an answer that does not save anything. A
  real model should say so; the mock just echoes. The system prompt does not mention notes.
- Turning writing tools on is a decision per environment, until approval for risky tools
  exists (chapter 21).

## Alternatives considered

- Remove the commands: one way to do it, but every note then costs two model calls, and
  saving depends on the model choosing the tool.
- Writing tools on by default: what people expect from "remember that", but a model that
  follows instructions inside a note or a pasted text could add or delete notes without
  anyone asking (docs/security.md, gap 8).
