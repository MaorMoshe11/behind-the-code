# Part B · A service

<div dir="rtl">

**חלק ב' · שירות**

</div>

The agent only runs when you run it, and forgets everything when it stops. This part turns it into a service other programs can call, with data that survives.

## Chapters

| # | Chapter | Time | What you learn | What the project gains |
|---|---|---|---|---|
| 4 | [How the network works](../workbook/chapter-04.html)<br>איך הרשת עובדת | 3–4 h | Client and server, HTTP by hand, status codes and headers, JSON, DNS, ports. | Small scripts that send raw HTTP and a tiny local server; you see what the SDK really sends. |
| 5 | [APIs](../workbook/chapter-05.html)<br>APIs | 4–5 h | REST, FastAPI, Pydantic schemas, API-key authentication, webhooks. | `POST /chat` and `GET /health`, generated API docs, and a minimal web chat page. |
| 6 | [Databases](../workbook/chapter-06.html)<br>בסיסי נתונים | 4–5 h | SQL, indexes, transactions; document stores, analytical stores and caches by contrast. | Conversations and messages stored through SQLAlchemy, so the agent remembers across restarts. |
| 7 | [Migrations](../workbook/chapter-07.html)<br>Migrations | 3–4 h | Schema changes on live data with Alembic, backfills, expand/migrate/contract, rollback. | A migration history; a new column added to existing data and backfilled; the app refuses to start on a database older than its code. |

## Where you end up

An HTTP API with authentication and a database whose schema changes safely.

The project as it should look after each chapter is in `checkpoints/chapter-04` to `checkpoints/chapter-07`. Solutions to the exercises are in `workbook/solutions/`.

## Printing

This part as one file: [`workbook/print/part-2.pdf`](../workbook/print/part-2.pdf), or `part-2.html` in the same folder.

[Back to the main README](../README.md)
