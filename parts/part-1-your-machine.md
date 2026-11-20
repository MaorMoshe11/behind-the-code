# Part A · Your machine

<div dir="rtl">

**חלק א' · המחשב שלכם**

</div>

You can write Python, but the code lives in one file on one computer. This part makes the project reproducible, versioned and trustworthy before anything else is built on it.

## Chapters

| # | Chapter | Time | What you learn | What the project gains |
|---|---|---|---|---|
| 1 | [Working environment](../workbook/chapter-01.html)<br>סביבת העבודה | 3–4 h | Terminal, virtual environments, dependencies and lock files, environment variables, the debugger. | A `chat.py` script in a `uv` project with `.env` and a mock mode that needs no API key. |
| 2 | [Git and GitHub](../workbook/chapter-02.html)<br>Git ו-GitHub | 4–5 h | Commits, branches, merge conflicts, pull requests, code review. | A git repository with a clean history; a `/reset` command built on a branch and merged; a local bare repository standing in for the remote. |
| 3 | [Code quality](../workbook/chapter-03.html)<br>איכות קוד | 5–6 h | Tests with pytest, linting with ruff, type hints with mypy, logging, error handling. | The script becomes an `agent/` package with a real client and a mock client, and a test suite. |

## Where you end up

A typed, tested, linted Python package under version control.

The project as it should look after each chapter is in `checkpoints/chapter-01` to `checkpoints/chapter-03`. Solutions to the exercises are in `workbook/solutions/`.

## Printing

This part as one file: [`workbook/print/part-1.pdf`](../workbook/print/part-1.pdf), or `part-1.html` in the same folder.

[Back to the main README](../README.md)
