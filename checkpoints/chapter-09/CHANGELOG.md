# Changelog

Every release of my-agent, newest first. Versions follow semantic versioning
(MAJOR.MINOR.PATCH); while the major version is 0, the API may still change.
New changes go under "Unreleased" in the pull request that makes them.

## [Unreleased]

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
