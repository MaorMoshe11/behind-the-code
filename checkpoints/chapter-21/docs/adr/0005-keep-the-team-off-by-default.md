# ADR 0005: keep the team off by default; turn it on per deployment only with an eval

Status: accepted (chapter 20). Date: 2026-11-19.

## Context

Since 0.19.0 a router can hand a big review ("go over my notes and earlier conversations
about the party") to a team: an orchestrator and two reading specialists that work at the
same time (`CHAT_TEAM=1`). Should the deployed service turn it on?

Measured in mock mode, on one review of six notes, one earlier conversation and two
memories, with `CHAT_MOCK_DELAY=0.5` (every model call takes half a second). Tokens are the
mock's count (a token per four characters), so only the comparison means something. Prices
are claude-opus-5-5's ($4 per million input tokens, $20 output, $5 written to the cache,
$0.20 read from it); claude-haiku-5-5 is $0.10 input and $0.50 output.

| Who answers the review | Model calls | Tokens | Cost | Time | Next message's context |
|---|---|---|---|---|---|
| One agent (0.18.0) | 2 | 2,140 | $0.014 | 1.0 s | 1,471 tokens |
| Team, one specialist after the other | 6 + router | 4,711 + ~100 | $0.033 | 3.6 s | 873 tokens |
| Team, in parallel | 6 + router | 4,711 + ~100 | $0.033 | 2.5 s | 873 tokens |
| Team, specialists and router on claude-haiku-5-5 | 6 + router | the same | about $0.015 | 2.5 s | 873 tokens |

With `CHAT_TEAM=1`, every ordinary message also pays the router: one more call (0.5 s in
the mock, about 100 tokens), before the chat answers.

## Decision

`CHAT_TEAM` stays `0` in staging and prod. On this project's tasks the team costs more than twice
the tokens and the money of one agent, takes longer even in parallel, and adds a call to
every message; what it buys (a smaller context for the rest of the conversation, specialists
that cannot write) is real but small at this size. We turn it on in a deployment only when
an eval (chapter 21) shows that it answers big reviews better than one agent, and then with
the specialists on a smaller model, measured on the same eval.

## Consequences

- Big reviews keep running in one agent's context, and stay in the conversation's history
  until compaction summarises them.
- The team stays in the code and in the tests, so trying it is one variable away.
- The router's cost argues for a different trigger later: an explicit command (for example
  `/review`) instead of a model call on every message.

## Alternatives considered

- Team on, specialists on `CHAT_MODEL`: the most expensive row, no measured gain in quality.
- Team on with a cheap worker model: close to the cost of one agent, but the answers of a
  smaller model are not measured yet. Revisit with the evals of chapter 21.
- One agent with a bigger step limit: the simplest; it does not shrink its own context.
