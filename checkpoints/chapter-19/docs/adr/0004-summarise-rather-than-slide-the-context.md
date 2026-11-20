# ADR 0004: summarise older turns rather than slide the window; keep CHAT_MAX_TURNS at 10

Status: accepted (chapter 19). Date: 2026-11-19.

## Context

Since 0.18.0 every call's context is assembled within a budget, the client asks for prompt
caching, and older turns can be summarised (compaction) or simply left out (`CHAT_COMPACT=0`,
a sliding window). Which policy should the deployed service use, and with how many turns?

Measured in mock mode: one conversation of 30 questions of about 40 words each, every model
call recorded (the agent's steps and the summaries), priced at claude-opus-5-5's input rates
($4 per million input tokens, $5 per million written to the cache, $0.20 per million read
from it). The tokens are the mock's count, so only the comparison means something; output
tokens are left out (the same in every row, except the summaries' few hundred).

| `CHAT_MAX_TURNS` | `CHAT_COMPACT` | Calls | Prompt tokens | Read from cache | With caching | Without |
|---|---|---|---|---|---|---|
| 100 (nothing trimmed) | 1 | 30 | 59,655 | 55,672 | $0.031 | $0.239 |
| 10 | 1 | 33 | 40,762 | 30,448 | $0.057 | $0.163 |
| 10 | 0 (sliding window) | 30 | 39,650 | 8,856 | $0.155 | $0.159 |
| 4 | 1 | 39 | 36,524 | 18,527 | $0.092 | $0.146 |

## Decision

Keep compaction on (`CHAT_COMPACT=1`) and `CHAT_MAX_TURNS=10`. Never run a sliding window with
caching: once the window is full, every call starts with a different turn, so the cache is
missed on every call and caching saves nothing (row 3). Compaction changes the start of the
context once every eight turns; in between, the cache is read.

## Consequences

- An extra model call every eight turns or so (the summary), and a slower answer on that turn.
- What the summary drops is gone from the model's view (the turns stay stored). Facts that must
  survive belong in long-term memory (`remember`), not in a summary.
- Not trimming at all is the cheapest with caching while the conversation is short, but the
  context grows without limit: slower calls, the window's end, and attention spread over old
  turns. The budget (`CHAT_CONTEXT_TOKENS`) is what bounds it.

## Alternatives considered

- A sliding window (`CHAT_COMPACT=0`): simplest, no extra call, but it loses the oldest turns
  silently and, with caching, costs about three times as much as compaction.
- The API's own compaction (beta `compact-2026-01-12`, `context_management` with
  `compact_20260112`): summarises on the server when the input reaches a threshold (150,000
  tokens by default). Less code, but the threshold is far above our budget, it works only with
  the real API (the mock and the tests could not show it), and it ties the conversation format
  to a beta. To reconsider once conversations get long.
