# Postmortem: "I deleted a conversation, it said nothing was deleted, and my notes are gone"

- **Date and duration:** 2026-11-18, 20:44:10 to 20:50:48 UTC (6.5 minutes), staging
- **Impact:** one tester lost the 3 notes of one conversation (2 she knew of, and one she had
  been told was not saved). For 6.5 minutes `/note` and `/notes` took about 6 s and then said
  notes were unavailable, or answered at once with the same message (circuit breaker).
  Chatting itself was not affected. Evidence: `examples/incident/`.
- **Detected by:** the tester's report at 20:55. The ticket alert NotesFailing was firing from
  about 20:49; no page alert fired.
- **Status:** resolved; the data loss bug is fixed (CHANGELOG, Unreleased, Fixed).

## Summary

The notes service was redeployed with a 2.5 second delay before every answer, longer than
the chat's 2 second timeout. When the tester deleted a conversation, the notes service
deleted its notes, but the chat gave up waiting before the answer came. The delete saga
treated "no answer" as "nothing happened": it compensated only the step before (it brought
the conversation back) and told the user nothing was deleted. The notes were gone.

## Timeline (UTC)

| Time | What happened | Evidence |
|---|---|---|
| 20:43:34 | A non-JSON message ("load-test ping") lands in `chat-events`; the worker parks it. Unrelated. | worker.log, ERROR dead letter, no request_id |
| 20:44:10 | The notes service restarts with a fault-injection delay of 2.5 s | notes.log, WARNING "fault injection: delay 2.5s" |
| 20:44:20 | Dana's `/note train at 9:40`: three attempts, each times out after 2 s; the notes service saves it once and replays it twice; Dana is told notes are unavailable | api.log and notes.log, request e2a8877d... |
| 20:44:30.7 | Dana deletes the conversation: archived | api.log, request c0dd8273... |
| 20:44:33.3 | The notes service: "deleted 3 notes", 200 after 2522 ms. The chat had already timed out (20:44:32.7) | notes.log |
| 20:44:36.9 | Two more attempts deleted 0; the saga fails, un-archives the conversation, answers 503 "nothing was deleted" | api.log |
| 20:44:39 | `/ready` says notes "ok" | ready.json |
| 20:44:41 | NotesFailing becomes pending; firing 5 minutes later (ticket) | alerts.json |
| 20:44:45 | A third failure opens the circuit breaker: later `/note` calls are refused at once (17 in all) | api.log "circuit open", metrics-after |
| 20:50:48 | The notes service restarts without the delay; notes work again | notes.log |
| 20:51:32 | Dana's conversation is back, with no notes | the report |

## Root cause and contributing factors

1. The saga runner assumed that a step that raised had changed nothing, so it never
   compensated the failed step itself. A timeout is not a "no": the outcome is unknown.
2. The compensation of "delete its notes" restored only the notes returned by the delete call,
   which never arrived.
3. A fault-injection setting reached a shared environment. It is refused in prod only.
4. The notes service's `/ready` checks its database, not its speed, so health checks stayed
   green; the chat's timeout (2 s) and the service's latency were never compared.
5. No alert watched data loss in the delete saga: "compensated" looked like success.

## What went well

- One request id led from the tester's error message to every line in both services.
- The circuit breaker limited the slow calls to 13; 17 calls failed at once instead.
- The notes service logged "deleted 3 notes" with the request id, which proved the loss.

## What went badly, and where we were lucky

- The user was told "nothing was deleted", which was false.
- The worker's ERROR at 20:43:34 and the kafka WARNING at startup drew attention first.
- Lucky: it happened in staging, to a tester, with test data.

## Actions

| Action | Kind | Owner | Ticket |
|---|---|---|---|
| Compensate the failed step too, from the notes listed before the delete (done) | prevent | chat | fix/saga-unknown-outcome |
| Refuse fault injection outside `local` (not only in prod) | prevent | notes | |
| Alert on `notes_calls_total{outcome="failed"}` latency vs. timeout; add `/metrics` to the notes service | detect | notes | |
| Soft delete in the notes service (restore by conversation, same ids) | mitigate | notes | |
| SLO for notes calls: 99% of calls answered within the 2 s timeout over 28 days; page when the 1 h burn rate would spend the month's budget in 2 days | detect | chat | |
