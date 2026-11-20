# Changelog

Every release of my-agent, newest first. Versions follow semantic versioning
(MAJOR.MINOR.PATCH); while the major version is 0, the API may still change.
New changes go under "Unreleased" in the pull request that makes them.

## [Unreleased]

### Added
- A circuit breaker in front of the notes service: after 3 failed calls in a row, `/note`
  answers at once for 30 seconds instead of waiting for every timeout.
- Contract tests for the notes service's v1 API (`notes-service/tests/test_contract.py`).
- `docs/architecture.md`: the services, who owns which data, and what happens when one is down.

## [0.11.0] - 2026-11-18

### Added
- A second service, `notes-service/` (version 0.1.0): short notes per conversation, with its
  own code, database, image and tests, and a versioned API (`/v1/notes`).
- `/note <text>` and `/notes` in the chat (terminal and `POST /chat`), through
  `agent/notes.py`: a 2-second timeout (`NOTES_TIMEOUT`), retries with backoff and jitter,
  and an `Idempotency-Key` per note. When the notes service is down, the chat still answers.
- `NOTES_URL`, `NOTES_API_KEY` (or `NOTES_API_KEY_FILE`). `/ready` reports `notes`, but
  does not depend on it.
- The notes service in `compose.yaml`, in `deploy/` (`NOTES_IMAGE_TAG`, two new secrets)
  and in CI (a `notes` job, and its image).

## [0.10.0] - 2026-11-18

### Added
- `GET /ready`: readiness, 503 when the database does not answer (`/health` stays liveness).
  The image checks itself with it (`HEALTHCHECK`), and reports its version and environment.
- `APP_ENV` (`local`, `staging`, `prod`). Outside `local`, `DATABASE_URL` is required.
- Secrets from files: `<NAME>_FILE` for `ANTHROPIC_API_KEY`, `AGENT_API_KEY` and the new
  `DATABASE_PASSWORD`.
- `deploy/`: staging and prod on this computer, with `scripts/make_secrets.py` and
  `scripts/deploy.py` (deploy, check, roll back).

### Changed
- On Postgres, a connection attempt gives up after 3 seconds, and pooled connections are
  checked before use.

## [0.9.0] - 2026-11-18

### Added
- CI on GitHub Actions: lint, type check and tests (also on Postgres) and an image build
  on every pull request (`.github/workflows/ci.yml`).
- `scripts/ci_local.py` runs the same commands on your computer.
- A release workflow: a tag `vX.Y.Z` builds the image `ghcr.io/<owner>/<repo>:X.Y.Z` and
  creates a GitHub release with these notes.

### Changed
- One Python version, 3.13, written in `.python-version` and used by uv, CI and the image.
- The API reports the version from `pyproject.toml` (it was written in `api.py` by hand).

## [0.8.0] - 2026-11-18

### Added
- A Dockerfile and `compose.yaml`: the API, its migrations and Postgres in containers.
- `scripts/copy_conversations.py`, and the migration tests on Postgres (`TEST_DATABASE_URL`).

Earlier versions were not recorded here.
