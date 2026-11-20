# Part E · Agents

<div dir="rtl">

**חלק ה' · סוכנים**

</div>

Until here the chat only talks. This part turns it into an agent that acts, then into several agents, and ends with what it takes to run one in production.

## Chapters

| # | Chapter | Time | What you learn | What the project gains |
|---|---|---|---|---|
| 16 | [What an AI agent is](../workbook/chapter-16.html)<br>מה זה AI agent | 4–5 h | Single call versus workflow versus agent, tool use, the agent loop, when not to build one. | The agent loop written by hand, with one read-only tool, a step limit and a trace of every step. |
| 17 | [Working with agents day to day](../workbook/chapter-17.html)<br>לעבוד עם סוכנים ביום-יום | 3–4 h | Coding agents: what to delegate, briefing, small steps, verifying, permissions. | No project change. You review an agent-made change with planted problems. |
| 18 | [Tools and integrations](../workbook/chapter-18.html)<br>Tools ו-integrations | 5–6 h | Tool design, a tool registry, structured outputs, the Model Context Protocol. | The notes service exposed as well-designed tools, a structured-output command, and an MCP server. |
| 19 | [Context and memory](../workbook/chapter-19.html)<br>Context ו-memory | 5–6 h | The context window as a budget, token counting, prompt caching, compaction, retrieval, long-term memory. | A context builder with a budget, compaction, prompt caching, conversation search and a per-client memory store. |
| 20 | [Multi-agent systems](../workbook/chapter-20.html)<br>Multi-agent systems | 5–6 h | Routing, orchestrator and workers, parallel work, handoffs, frameworks, when it is worth the cost. | A router, an orchestrator and two specialist subagents in plain Python, with one budget for the whole run. |
| 21 | [Agents in production](../workbook/chapter-21.html)<br>סוכנים בייצור | 6–7 h | Evals, tracing of agent runs, guardrails, prompt injection, human approval, cost. | An eval runner in CI, run traces with cost, guardrails, human approval for writing tools, a local prompt-injection demonstration with its defences, and production model settings. The project is released as 1.0.0. |

## Where you end up

A multi-agent system with evals, approvals and cost tracking: the finished project.

The project as it should look after each chapter is in `checkpoints/chapter-16` to `checkpoints/chapter-21`. Solutions to the exercises are in `workbook/solutions/`.

## Printing

This part as one file: [`workbook/print/part-5.pdf`](../workbook/print/part-5.pdf), or `part-5.html` in the same folder.

[Back to the main README](../README.md)
