# Part C · From your machine to the world

<div dir="rtl">

**חלק ג' · מהמחשב לעולם**

</div>

The service works on your computer. This part packages it, checks every change automatically, and runs it in more than one environment with a way back.

## Chapters

| # | Chapter | Time | What you learn | What the project gains |
|---|---|---|---|---|
| 8 | [Containers](../workbook/chapter-08.html)<br>Containers | 4–5 h | Docker images and layers, a Dockerfile, Docker Compose, volumes. | The API and Postgres start with one command; the database moves to Postgres through `DATABASE_URL`. |
| 9 | [CI/CD](../workbook/chapter-09.html)<br>CI/CD | 4–5 h | Pipelines, GitHub Actions, required checks, versioning, releases. | A workflow that lints, type-checks, tests against Postgres and builds the image on every pull request; a release workflow; a script that runs the same checks locally. |
| 10 | [Deployment and cloud](../workbook/chapter-10.html)<br>Deployment וענן | 4–5 h | Environments as configuration, secrets, liveness and readiness, rollback, deployment strategies, cloud building blocks, infrastructure as code. | A local staging and prod from the same image, a deploy script, and a rollback after a deliberately bad release. |

## Where you end up

A versioned container image, checked by CI and deployed to two environments.

The project as it should look after each chapter is in `checkpoints/chapter-08` to `checkpoints/chapter-10`. Solutions to the exercises are in `workbook/solutions/`.

## Printing

This part as one file: [`workbook/print/part-3.pdf`](../workbook/print/part-3.pdf), or `part-3.html` in the same folder.

[Back to the main README](../README.md)
