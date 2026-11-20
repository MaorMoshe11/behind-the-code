# Part D · A system

<div dir="rtl">

**חלק ד' · מערכת**

</div>

One service is not a system. This part adds a second service, asynchronous work, visibility into what is running, security, and the way a team carries work from a ticket to production.

## Chapters

| # | Chapter | Time | What you learn | What the project gains |
|---|---|---|---|---|
| 11 | [Architecture](../workbook/chapter-11.html)<br>ארכיטקטורה | 5–6 h | Monolith versus microservices, timeouts, retries with backoff, idempotency keys, circuit breakers, graceful degradation. | A notes service with its own database and container, called over HTTP through a typed client that survives a slow, failing or half-successful call. |
| 12 | [Messaging and pipelines](../workbook/chapter-12.html)<br>Messaging ו-pipelines | 5–6 h | Kafka, queues versus streams, delivery guarantees, the saga pattern, Airflow, batch versus streaming. | Events published to Kafka and a worker that consumes them; a delete saga across two services with compensation; a nightly report as an Airflow DAG. |
| 13 | [A live system](../workbook/chapter-13.html)<br>מערכת חיה | 5–6 h | Structured logs with request ids, metrics, tracing, alerts, incidents and postmortems. | JSON logs that follow one request across services, a `/metrics` endpoint, Prometheus alert rules with a runbook, and a real incident to diagnose from saved evidence. |
| 14 | [Security](../workbook/chapter-14.html)<br>אבטחה | 5–6 h | Threat modelling, secrets, authentication versus authorization, least privilege, input validation, dependency audit, rate limiting, personal data. | Per-client keys, conversations owned by their caller, a non-root container, a rate limiter, and security checks in CI. |
| 15 | [Working in a team](../workbook/chapter-15.html)<br>עבודה בצוות | 5–7 h | Tickets and acceptance criteria, design docs and ADRs, estimation, definition of done, documentation, review. | One vague ticket carried to a merged pull request, with the design doc, estimate and PR description kept as examples. |

## Where you end up

Two services, a broker and a worker, observable and hardened, with the paperwork a team expects.

The project as it should look after each chapter is in `checkpoints/chapter-11` to `checkpoints/chapter-15`. Solutions to the exercises are in `workbook/solutions/`.

## Printing

This part as one file: [`workbook/print/part-4.pdf`](../workbook/print/part-4.pdf), or `part-4.html` in the same folder.

[Back to the main README](../README.md)
