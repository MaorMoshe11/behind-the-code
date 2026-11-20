# AGENT-42: Readable conversation titles

An example ticket from chapter 15: how it arrived, and how it looked after clarifying it.

## As it arrived

> **Conversation titles look broken in our list.**
>
> Reported by Dana (the `dana` client). No description.

## After clarifying

### Context

Dana's app shows the caller's conversations in a sidebar, one line each, from
`GET /conversations`. A title is the first 50 characters of the first message
(`agent/conversations.py`), so today:

- it is cut in the middle of a word: `Could you explain how database indexes work in Pos`;
- a pasted message keeps its line breaks: `Here is my error:\nTraceback (most recent call last`,
  which breaks the one-line layout;
- nothing shows that the title was cut.

The terminal (`--continue`) prints the same titles. Dana could clean them up in her app,
but then every client would have to do the same, so the fix belongs in the server.

### Acceptance criteria

1. A new conversation's title has no line breaks, tabs or repeated spaces: all whitespace
   becomes one space, and the ends are trimmed.
2. A title is at most 50 characters, including the ending `...`.
3. A longer first message is cut after the last whole word that fits, and ends with `...`.
   A first word longer than the limit is cut inside the word (a long URL, for example).
4. A first message that fits is the whole title, without `...`.
5. A first message of whitespace only leaves the title `New conversation`.
6. Existing conversations get the new title from a migration, when their title is still the
   automatic one (the start of their first message). Any other title is left as it is.
7. Downgrading the migration puts the old titles back.
8. The API does not change: same endpoints, same fields.

### Out of scope

- Renaming a conversation (a new endpoint; a separate ticket if Dana needs it).
- Titles written by the model (a call per conversation, costs money; later, maybe).
- A different length than 50, or a list in our own chat page.

### Estimate

5 to 8 hours (one working day, maybe a day and a half). Breakdown and the comparison with
what happened: `docs/design/2026-11-19-readable-titles.md`, "Estimate".

### Links

- Design: `docs/design/2026-11-19-readable-titles.md`
- Pull request: `fix/readable-titles` (description in `examples/team/pr-readable-titles.md`)
