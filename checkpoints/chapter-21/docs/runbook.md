# Runbook

One entry per alert in `monitoring/alerts.yml`. Written for the person who is woken up:
what the alert means, what to look at first, and what to do. Mitigate first (make users
stop suffering), find the cause after.

Useful everywhere:

- Logs of one service: `docker compose logs <service> --since 30m --no-log-prefix`
- Every line of one request: `docker compose logs api notes worker --no-log-prefix | Select-String <request id>`
- The api's metrics: `curl.exe -s http://127.0.0.1:8000/metrics`
- Prometheus (with `--profile monitoring`): http://127.0.0.1:9090, tab Alerts

## ApiDown

Prometheus cannot scrape the api for a minute. Users get nothing at all.

1. `docker compose ps api`: is it running, restarting, unhealthy?
2. `docker compose logs api --tail 50`: a crash at startup is usually a `ConfigError` or the
   database (`/ready` answers 503 when the database is down).
3. Mitigate: if a deploy just happened, roll back (README, "Deploy"). Otherwise restart it.

## ChatErrors

More than 5% of `/chat` and `/conversations` requests answer 5xx for 5 minutes.

1. Which status and route? In Prometheus:
   `sum by (route, status) (rate(http_requests_total{status=~"5.."}[5m]))`
2. 502 on `/chat`: the model fails. Check `llm_errors_total` by `reason` (auth, timeout,
   connection, rate_limited, status) and the api's ERROR lines.
3. 503 on `DELETE /conversations/...`: the notes service; see NotesFailing.
4. 500: a bug. Take a `request_id` from an ERROR line and read all its lines.
5. Mitigate: a recent deploy? Roll back. The model's provider down? Nothing to roll back:
   say so on the status page and wait.

## ChatSlow

The 95th percentile of `/chat` is above 3 seconds for 10 minutes.

1. Is it the model? Compare `llm_request_duration_seconds` with
   `http_request_duration_seconds{route="/chat"}`. If they match, the time is in the model.
2. If not: `/note` and `/notes` go to the notes service and wait up to about 7 s. Look at
   access lines with a high `duration_ms`, then at their `request_id`.
3. Mitigate: a smaller `NOTES_TIMEOUT` ends the wait sooner; the breaker already fails fast
   after 3 failures.

## NotesFailing

More than 10% of calls to the notes service fail or are refused by the circuit breaker.

1. `notes_circuit_open`: 1 means the chat has stopped calling for now.
2. The notes service's own lines: `docker compose logs notes --since 15m --no-log-prefix`.
   Compare its `duration_ms` with the chat's timeout (2 s). A notes service that answers
   200 after the chat gave up looks healthy from inside and broken from outside.
3. `/ready` of the notes service checks only its database. It can be "ready" and still slow.
4. Its startup lines: a `fault injection` warning, or a new version.
5. Deleting conversations fails (503) while this alert is on. Check whether any deletion
   lost notes: the notes service logs `deleted N notes` with the request id.

## SagaCompensationFailed

A saga failed and could not undo what it had done. Some data is half changed: for the
delete saga, a conversation may be archived (hidden) with its notes gone, or the reverse.

1. Find the `COMPENSATION FAILED` line in the api's logs; its `request_id` leads to the
   conversation (the access line of the same request has the path).
2. Fix the data by hand, then write a postmortem: this alert means a design gap.

## EventsLost

The api could not deliver events to Kafka (the dual write of chapter 12). The chat works;
usage statistics miss those events and will not get them back by themselves.

1. `docker compose ps kafka`, and the api's `event lost` lines.
2. After Kafka is back, statistics stay wrong until rebuilt from a source of truth. The
   outbox (`docs/architecture.md`) is the real fix.

## WorkerBehind

The usage worker has more than 100 events it has not committed, for 15 minutes.

1. `docker compose ps worker`: is it running? Restarting in a loop?
2. Its logs: `dead letter` lines are fine (it moves on); a crash before every commit is not.
3. Lag that grows steadily while the worker runs: it is too slow; add a worker
   (`--scale worker=2`, up to one per partition).

## ModelSpendHigh

The model calls cost more than the hourly budget (`llm_cost_dollars_total`, priced by
`agent/prices.toml`).

1. Who: `sum by (client) (increase(llm_cost_dollars_total[1h]))` and the same `by (agent)`.
   One client, or the team (`agent="orchestrator..."`), or everyone?
2. Why: in the logs of that hour, the `"model replied"` lines with the largest `cost_usd`;
   open their traces (`CHAT_TRACE_DIR`, `uv run python -m agent.tracing <file>`). A loop that
   hits its step limit, a huge context, or simply more users?
3. Stop the bleeding if it is abuse or a loop: lower `CHAT_RATE_LIMIT` for everyone, or remove
   the client's key from `AGENT_API_KEYS`; `CHAT_TEAM=0` if the team is the cause.
4. If it is real use, the budget is the thing to change, after a decision about money.
