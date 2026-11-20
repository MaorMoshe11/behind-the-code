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
2. Run the checks from README.md (pytest, ruff, mypy) and fix everything they report.
   A bug fix comes with a test that fails before the fix and passes after it.
3. Push the branch and open a pull request into `main`. Describe what changed, why, and how you tested it.
4. At least one other person reviews it. Answer every comment, by a change or by an explanation.
5. After approval, merge it and delete the branch.
