# Security: the threat model

Who could do what to this system, and what stops them. Update it whenever a service, an
entry point or a kind of data is added. Last reviewed: 0.14.0.

## What we protect (assets)

| Asset | Where it lives | Why it matters |
|---|---|---|
| Conversations and messages | chat Postgres (`db`), its backups | People write private things to a chat. Personal data. |
| Notes | notes Postgres (`notes-db`) | The same. |
| The Anthropic API key | `.env` / a secret file, the api's memory | Whoever holds it spends our money. |
| Client keys | the clients; the server keeps SHA-256 hashes | Whoever holds one acts as that client. |
| Service secrets | `NOTES_API_KEY`, database passwords, `METRICS_TOKEN` | Each opens one door inside the system. |
| Availability and cost | the api, the model | Every `/chat` costs money; a flood costs a lot. |
| Usage statistics, logs, metrics | worker volume, stdout, Prometheus | Ids and counts only; they still describe our users. |

## Where requests come in (entry points)

| Entry point | Who may use it | How it is checked |
|---|---|---|
| `POST /chat`, `/conversations...` | clients with a key | `X-API-Key` -> hash -> client; owner check (404 for others); Pydantic types and sizes; ids `^[0-9a-f]{32}$`; body <= 64 KiB; 30 `/chat` per minute per client |
| `GET /` (chat page) | anyone (it is static) | renders text with `textContent`, never as HTML; key in `sessionStorage` |
| `GET /metrics` | Prometheus only | `Authorization: Bearer <METRICS_TOKEN>`; 404 when unset |
| `GET /health`, `/ready` | anyone who reaches the port | reveal version and environment only |
| notes `/v1` | the chat service only | `NOTES_API_KEY`; Pydantic limits; no host port in deploy |
| Kafka `chat-events` | containers in the compose network | nothing: PLAINTEXT, no auth (gap) |
| worker port 9100 | the compose network | nothing (no host port) |
| The model's replies | the model | treated as untrusted text: never run, never rendered as HTML |
| Text sent to the model | users | untrusted: a user can try to steer the model (prompt injection, chapter 21) |
| Tool calls the model asks for (0.17) | the model | the input is validated (Pydantic, unknown fields refused); the conversation is fixed by the code; writing tools only with `CHAT_WRITE_TOOLS=1`; every call logged |
| The MCP server (stdio, 0.17) | the process that starts it | no network port; one conversation, fixed at start; the same tools and checks as the chat |

## Trust boundaries

1. The internet (or the reader's browser) and the api: everything that crosses it is checked.
2. The api and the model provider: we send user text out; what comes back is input too.
3. The api and the notes service / Kafka / databases: today, one network where every
   container is trusted. A container that is broken into reaches all of them.
4. Developers' laptops and CI and the deployed environments: secrets cross here, which is
   why they live in files outside git and the image.

## What we did (0.14)

- Keys per client, stored as hashes; conversations owned by a client (authorization).
- `/metrics` behind its own token; Prometheus reads it as a secret.
- Input limits (ids, sizes), rate limit with `Retry-After`.
- Containers as user `app`; a two-stage image without uv.
- Secret scanning (gitleaks) and dependency audit (`uv audit`) in CI; actions pinned to SHAs.
- Fault injection refused in prod (notes switches, worker crash switch).
- Logs carry ids, counts and durations; never message text, notes or keys (a test checks).

## Known gaps, most important first

1. **Kafka has no authentication or encryption.** Anyone in the network can read and write
   events. Fix: SASL (SCRAM) users per producer and consumer, ACLs per topic, TLS.
2. **One static key between the chat and the notes service, and one network.** Fix: a key per
   calling service, rotated; or mTLS (each service proves who it is with a certificate).
3. **The api's database user owns the tables** (and in local compose it is a superuser). Fix: a
   role for the app with only SELECT, INSERT, UPDATE, DELETE; the owner only for `migrate`
   (tried in chapter 14, exercise 4; not wired into compose).
4. **No TLS inside the system.** HTTPS ends at the edge in production (a proxy or the platform);
   traffic between containers is plain HTTP.
5. **The rate limit lives in one process.** Two copies of the api allow twice as much. Fix: limit
   at the edge, or a shared counter (Redis).
6. **Keys never expire.** Fix: rotation dates, or short-lived tokens (OAuth 2.0 / JWT) from an
   identity provider, with the api checking signatures.
7. **No retention policy.** Conversations live until a person deletes them; Kafka keeps events
   7 days; backups keep everything. Decide a period, delete older data, and say so to users.
8. **Prompt injection** is not handled yet (chapter 21). Since 0.17 it matters more: with
   `CHAT_WRITE_TOOLS=1`, text in a note or a message could lead the model to add or delete
   this conversation's notes. Tool results are untrusted input. Fix: approval for writing
   tools, and the injection tests of chapter 21.

## Personal data

Messages and notes are personal data. We keep them only to show the conversation again; we do
not log them, and events carry counts, not text. Deleting a conversation (the delete saga)
removes its messages, its notes and its usage row. Not legal advice: what a law (for example
the GDPR, or Israel's Privacy Protection Law) requires of a real service is for a lawyer.

## Tools

- gitleaks (secrets in git history): https://github.com/gitleaks/gitleaks/releases, the
  `windows_x64.zip`; check its SHA-256 against the release's `checksums.txt`.
- `uv audit --locked --preview-features audit` (known vulnerabilities; experimental in uv 0.11).
