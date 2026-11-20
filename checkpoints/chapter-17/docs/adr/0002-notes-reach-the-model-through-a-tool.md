# ADR 0002: Notes reach the model through a tool, in a hand-written loop

Status: accepted (chapter 16). Date: 2026-11-19.

## Context

Users ask the chat about what they saved with `/note` ("what did I save about milk?"). The
model only sees the messages we send, so it cannot know. Two ways to give it the notes:

- A workflow: our code always fetches the notes and puts them into the prompt, then makes one
  model call. Order fixed by us.
- An agent: the model gets a `list_notes` tool and decides whether to call it; our code runs
  the call and sends the result back, in a loop, until the model answers.

Measured in mock mode with three notes. The tokens are the mock's made-up count (about one
per four characters), so only the comparison means something:

| Message | Workflow | Agent |
|---|---|---|
| "hello" | 1 model call, 1 notes call, 31 input tokens | 1 model call, 0 notes calls, 128 input tokens (the tool definition) |
| "What did I save in my notes about milk?" | 1 model call, 1 notes call, 39 | 2 model calls, 1 notes call, 364 |

## Decision

The agent loop (`agent/loop.py`) with one read-only tool, `list_notes`, at most
`CHAT_MAX_STEPS` model calls per message. Written by hand, without a framework or the SDK's
tool runner, so every step can be read, logged and tested.

## Consequences

- Most messages are not about notes; they make no notes call, and a notes outage does not
  slow them (the workflow calls the notes service on every message, up to about 7 s when it
  is down).
- The model chooses a search, so a long list of notes is not sent whole.
- Every model call costs more: the tool definition is sent each time, and a notes question
  costs two calls, each sending the whole conversation again.
- Less predictable: the model may not call the tool when it should, or call it when it need
  not. Tests can check the loop with the scripted mock, not the model's choices (evals,
  chapter 21).
- The tool requests and results are not saved (chapter 19).

## Alternatives considered

- The workflow above: cheaper per message and fully predictable, and the better choice if
  most messages were about notes, or if there were only ever a few short notes.
- A framework or the SDK's tool runner: less code, but the loop is the thing this project
  must understand first. Revisit when there are several tools (chapter 18).
