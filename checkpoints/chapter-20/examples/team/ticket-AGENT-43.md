# AGENT-43: Delete old conversations

An example from chapter 15, exercise 1: a vague ticket, the questions, and the clarified ticket.

## As it arrived

> **We should delete old conversations.**
>
> From the security review (`docs/security.md`, gap 7: no retention policy).

## Questions asked, and the answers

1. How old is "old", and counted from what: the start, or the last message?
   Last message: a conversation in use is never deleted. 90 days, as a setting.
2. Who decides the period, and does it differ per client? One period for everyone, for now.
3. Deleted how: the same way as `DELETE /conversations/{id}` (with its notes)? Yes, the saga,
   so the notes go too and every deletion is one `conversation.deleted` event.
4. What about the usage statistics, Kafka (7 days) and backups? Usage rows hold counts only and
   stay. Kafka expires on its own. Backups: a separate ticket.
5. When does it run, and where? Once a night. Where is a design question.
6. Must users be told? Yes: one line in the README / terms. Not in this ticket.

## Clarified

### Context

Conversations live until someone deletes them (`docs/security.md`, gap 7). Messages are
personal data; we keep them only to show the conversation again.

### Acceptance criteria

1. A conversation whose last message is older than `CHAT_RETENTION_DAYS` (default 90) is
   deleted, with its notes, by the same saga as `DELETE /conversations/{id}`.
2. A conversation with a newer message is never touched; neither is one without messages
   that was created less than the period ago.
3. It runs once a night, and running it twice deletes nothing more.
4. Each run logs how many conversations it deleted and how many failed (ids, never content),
   and a metric counts both; a failure does not stop the run.
5. Archived conversations left behind by a failed saga are finished by the same run.
6. `docs/security.md` gap 7 says what is now done and what is left (backups).

### Out of scope

- Backups. A period per client. Telling the users.

### Design

Needed (a new scheduled process, and it deletes data): see
`docs/design/2026-11-20-conversation-retention.md`.
