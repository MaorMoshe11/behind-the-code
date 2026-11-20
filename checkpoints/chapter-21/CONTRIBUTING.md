# Contributing

How we work on this project with git.

## Branches

- `main` always works. Nobody commits to it directly.
- Every change starts on a short-lived branch from an up-to-date `main`:
  `feature/<name>` for new behaviour, `fix/<name>` for bugs, `docs/<name>` for documentation.
- A branch lives for days, not weeks. Small branches are easier to review and to merge.

## Commits

- One commit = one logical change.
- Message: a short summary line in the imperative mood ("Add /reset command", not "added stuff").
- Never commit `.env`, `.venv/` or anything with a secret in it. `.gitignore` covers the usual ones.

## Pull requests

1. Before opening a pull request, update your branch: `git fetch`, then `git rebase origin/main`.
2. Run the checks on your computer first: `uv run --locked python scripts/ci_local.py`
   (README.md, "Checks and CI"). A bug fix comes with a test that fails before the fix
   and passes after it.
3. Push the branch and open a pull request into `main`. Describe what changed, why, and how you tested it
   (GitHub fills in `.github/pull_request_template.md`). Link the ticket.
   Write what changed for the users of the agent under "Unreleased" in CHANGELOG.md.
4. Wait for CI. Both checks, "Lint, types and tests" and "Build the image", must be green:
   `main` accepts a pull request only when they are. Read a red check in its log and fix it
   on the branch; never skip it.
5. At least one other person reviews it. Answer every comment, by a change or by an explanation.
6. After approval, merge it and delete the branch.

## Definition of done

A change is done when it is merged and every line below is true, or the pull request says
why it does not apply:

- The ticket's acceptance criteria hold, each one checked by a test or by hand (say which).
- New behaviour has tests; a bug fix has a test that failed before the fix.
- `ci_local.py` is green, with Postgres for the migration tests.
- A change to tables or stored data has a migration that works with the version before it,
  and a downgrade.
- A new setting is in `.env.example`, in the README table, and in `deploy/*.env` if needed.
- A new way to fail is logged (ids and counts, never content) and, when it matters, counted
  in a metric, with an alert and a runbook entry.
- No secret and no user content in code, logs or events; new input is validated; it is
  decided who may call a new endpoint.
- README, `docs/` and CHANGELOG ("Unreleased") say what changed.
- It can be rolled back (see "Deploying").

A change that needs a decision first (stored data, a new service, a new dependency, an API
change) starts with a short design doc in `docs/design/`.

## When main is red

A red `main` stops everyone: every new branch starts from broken code. Whoever merged the
change that broke it fixes it first. If the fix takes more than an hour, revert the change
(`git revert`) and fix it on a branch.

## Releases

Versions follow semantic versioning, MAJOR.MINOR.PATCH:

- PATCH (0.9.0 to 0.9.1): a bug fix; every client keeps working unchanged.
- MINOR (0.9.0 to 0.10.0): something new that old clients can ignore: a new endpoint,
  a new optional field, a new environment variable with a default.
- MAJOR (1.x to 2.0.0): a client or an operator must change something: an endpoint or a
  field removed or renamed, a new required environment variable. While the version starts
  with 0, such a change bumps the minor version and is listed first in the changelog.

To release, from an up-to-date `main` with green CI:

1. In a pull request, move the "Unreleased" notes into a new section `## [X.Y.Z] - date`
   in CHANGELOG.md, set `version = "X.Y.Z"` in pyproject.toml, and run `uv lock`.
2. After it is merged: `git tag -a vX.Y.Z -m "my-agent X.Y.Z"`, then `git push origin vX.Y.Z`
   (and to `github`, which runs the release workflow).
3. The release workflow checks the tag, builds and pushes the image, and creates the release.
   A tag is never moved or reused: a broken release is fixed by the next version.

## Deploying

Staging and prod are described in `deploy/` (README.md, "Deploy"). What runs where is the
`IMAGE_TAG` line of `deploy/<environment>.env`, so every deploy is a commit on `main`.

1. Only an image of a release is deployed: `my-agent:X.Y.Z`, built from the tag `vX.Y.Z`.
   An image is never rebuilt under the same tag.
2. Staging first. Set `IMAGE_TAG`, commit ("Deploy X.Y.Z to staging"), and run
   `uv run python scripts/deploy.py staging`. Then try what changed, as a user would.
3. Prod only after staging was checked, with the same image: set `IMAGE_TAG` in
   `deploy/prod.env`, commit, `uv run python scripts/deploy.py prod`.
4. If `deploy.py` fails, or users see errors after a deploy: roll back first, investigate
   after. `git revert` the deploy commit and run `deploy.py <environment> --skip-migrations`.
   A rollback never runs migrations, and never runs `alembic downgrade` on prod data.
5. Every migration must work with the version before it: expand in one release, contract
   (drop or rename what the old version uses) only in a later one, after the old version
   can no longer come back.
6. A fix after a rollback is a new version (X.Y.Z+1), deployed like any other. It keeps
   every migration that already ran somewhere, unchanged.
7. Secrets live only in `deploy/secrets/` (created by `scripts/make_secrets.py`), never in
   git, in an env file or in the image. A secret that leaked is rotated at once.

## Secrets and dependencies

- Never commit a secret, not even "for a minute": git keeps every version. Run
  `gitleaks git -v --redact .` before you push; CI runs it on every pull request.
- If a secret was committed anyway: **rotate it first** (make a new one, revoke the old), then
  tell the team, then clean the history if it was never pushed. A pushed secret is public.
- A new dependency is a decision: check who maintains it and how widely it is used. `uv audit`
  runs in CI; a finding is fixed by upgrading (`uv lock --upgrade-package <name>`) in its own PR.
- Updates: once a month, one PR that upgrades the lock file, with the tests and the audit green.
