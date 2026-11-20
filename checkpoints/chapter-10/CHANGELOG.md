# Changelog

Every release of my-agent, newest first. Versions follow semantic versioning
(MAJOR.MINOR.PATCH); while the major version is 0, the API may still change.
New changes go under "Unreleased" in the pull request that makes them.

## [Unreleased]

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
