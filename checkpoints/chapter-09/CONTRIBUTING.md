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
3. Push the branch and open a pull request into `main`. Describe what changed, why, and how you tested it.
   Write what changed for the users of the agent under "Unreleased" in CHANGELOG.md.
4. Wait for CI. Both checks, "Lint, types and tests" and "Build the image", must be green:
   `main` accepts a pull request only when they are. Read a red check in its log and fix it
   on the branch; never skip it.
5. At least one other person reviews it. Answer every comment, by a change or by an explanation.
6. After approval, merge it and delete the branch.

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
