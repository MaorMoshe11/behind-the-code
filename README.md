# Behind the Code · מאחורי הקוד

<div dir="rtl">

**חוברת עבודה בעברית על כל מה שמתכנתים עושים חוץ מלכתוב קוד: מהמחשב שלכם ועד מערכת שרצה בענן, ועד סוכני AI בייצור.**

החוברת מיועדת למי שכבר יודע לכתוב Python ומכיר מודלי שפה, אבל עוד לא עבד בצוות פיתוח. ההסברים בעברית. הקוד, הפקודות והמונחים המקצועיים באנגלית, כי כך תפגשו אותם בעבודה. כדי להתחיל, הורידו את המאגר ופתחו את הקובץ `workbook/index.html` בדפדפן.

</div>

A hands-on workbook, written in Hebrew, for people who can already write Python and know
their way around LLMs, but have not yet worked on a software team. It teaches everything
around the code: environments, git, testing, APIs, databases, migrations, containers,
CI/CD, deployment, architecture, messaging, observability, security and teamwork, and then
AI agents: what they are, how to work with them, how to build one, and how to build a
multi-agent system with an orchestrator.

Explanations are in Hebrew. Code, commands and technical terms are in English.

## One project, 21 chapters

A single project runs through the whole workbook: a chat agent that talks to Claude. It
starts as one Python file. Each chapter adds the one layer a real team would have needed
next, so every concept arrives as the answer to a problem you have just felt.

By the last chapter that file has become two services with their own databases, a message
broker and a worker, running in containers, checked by CI, deployed to two environments,
observable and hardened, and driven by an agent loop with tools, memory, an orchestrator
with subagents, evals and human approval.

Every exercise works in **mock mode**: no API key, no account, no cost.

## The five parts

| Part | Chapters | In one line | Time |
|---|---|---|---|
| [A · Your machine](parts/part-1-your-machine.md) | 1–3 | Environment, git, tests: a project you can trust | 12–15 h |
| [B · A service](parts/part-2-a-service.md) | 4–7 | HTTP, an API, a database, migrations | 14–18 h |
| [C · From your machine to the world](parts/part-3-from-your-machine-to-the-world.md) | 8–10 | Containers, CI/CD, deployment | 12–15 h |
| [D · A system](parts/part-4-a-system.md) | 11–15 | Architecture, messaging, observability, security, teamwork | 25–31 h |
| [E · Agents](parts/part-5-agents.md) | 16–21 | The agent loop, tools, memory, multi-agent, production | 28–34 h |

About 90 to 115 hours in all, exercises included.

### All chapters

| # | Chapter | Topics |
|---|---|---|
| 1 | סביבת העבודה | terminal, virtual environments, dependencies, environment variables, debugger |
| 2 | Git ו-GitHub | commits, branches, pull requests, code review |
| 3 | איכות קוד | tests, linting, type hints, logging, error handling |
| 4 | איך הרשת עובדת | client/server, HTTP, JSON, DNS, ports |
| 5 | APIs | REST, FastAPI, schemas, authentication, webhooks |
| 6 | בסיסי נתונים | SQL, indexes, transactions, document stores, caching |
| 7 | Migrations | schema changes, Alembic, backfills, rollback |
| 8 | Containers | Docker, images, Dockerfile, docker-compose |
| 9 | CI/CD | pipelines, GitHub Actions, releases |
| 10 | Deployment וענן | environments, cloud basics, secrets, infrastructure as code |
| 11 | ארכיטקטורה | monolith vs. microservices, sync vs. async, idempotency |
| 12 | Messaging ו-pipelines | Kafka, queues, saga pattern, Airflow, batch vs. streaming |
| 13 | מערכת חיה | logs, metrics, tracing, alerts, incidents |
| 14 | אבטחה | secrets, least privilege, input validation, sensitive data |
| 15 | עבודה בצוות | tickets, design docs, estimation, documentation |
| 16 | מה זה AI agent | LLM call vs. workflow vs. agent, the agent loop, when not to build one |
| 17 | לעבוד עם סוכנים ביום-יום | coding agents, briefing, reviewing and verifying agent work |
| 18 | Tools ו-integrations | tool use, tool design, structured outputs, MCP |
| 19 | Context ו-memory | context window, prompt caching, compaction, retrieval, long-term memory |
| 20 | Multi-agent systems | orchestrators, subagents, routing, parallel work, handoffs, frameworks |
| 21 | סוכנים בייצור | evals, tracing, guardrails, human in the loop, prompt injection, cost |

## How to use it

1. Download or clone this repository. GitHub shows HTML files as source code, so the
   chapters are read from your own copy.
2. Open `workbook/index.html` in a browser. Nothing needs to be installed to read.
3. Work in order. Each chapter starts from the project as the previous one left it.
4. Type the commands yourself. Check boxes and write answers on the page: they are saved
   in that browser only.

Every chapter has the same shape: the problem, a map of the concept, the explanation, a
guided example you type along with, five to seven exercises, a self-check, a
troubleshooting table and a glossary. Solutions are on a separate page per chapter.

### On paper

Every chapter prints cleanly from its "הדפסה" button. Ready-made printable editions are in
[`workbook/print/`](workbook/print/): the whole book in one file (`book.pdf`, about 760
pages with the solutions) and one booklet per part (`part-1.pdf` to `part-5.pdf`). The same
files exist as self-contained HTML. To rebuild them after a change:

```
python tools/build_book.py --pdf
```

## What is in this repository

| Folder | Contents |
|---|---|
| `workbook/` | The 21 chapters, their solutions pages, the styles, and the printable editions |
| `parts/` | A short guide to each of the five parts |
| `starter/` | The three files you copy to begin the project in chapter 1 |
| `checkpoints/` | The whole project as it should look at the end of each chapter, to compare with yours. `checkpoints/chapter-21` is the finished project, with its own README |
| `tools/` | The script that builds the printable editions |

## What you need

- Windows 10 or 11. The commands are written for PowerShell. The ideas are the same on
  macOS and Linux, but the commands are not adapted for them.
- Python knowledge at the level of writing functions and classes.
- Each chapter lists the tools it needs and how to install them: `uv`, git, VS Code,
  Docker Desktop from chapter 8.
- A Claude API key is optional. With one, the agent gives real answers; without one, mock
  mode runs everything.

## How it was checked, and what was not

The project was rebuilt from the previous checkpoint for every chapter by following the
chapter's own text, and the commands and outputs shown come from those runs. The finished
project passes its tests, linting, type checks and offline evals from a clean copy.

Some things could not be run while writing, and are written from knowledge:

- **Real Claude API calls.** Everything was run in mock mode. Request and response shapes
  follow Anthropic's API reference.
- **Anything on GitHub itself** in chapters 2 and 9: pull request screens, Actions runs,
  branch protection, pushing an image to the registry.
- **The cloud walkthrough and the Terraform example** in chapter 10, which are reading
  material.
- **Installing Docker Desktop** in chapter 8, and Airflow's scheduler and web interface in
  chapter 12 (the DAG itself was run once).

If you find a mistake, please open an issue.

## License

The workbook text (chapters, solutions, printable editions, READMEs) is licensed under
[CC BY 4.0](LICENSE-CC-BY-4.0): share and adapt it freely, with credit. The code
(`checkpoints/`, `starter/`, `tools/`, and the samples inside the chapters) is licensed
under the [MIT License](LICENSE-MIT). See [`LICENSE`](LICENSE).
