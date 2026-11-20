# The image of the agent's HTTP service, built in two stages. The first stage has uv and
# installs the locked packages; the second gets only the result. uv, and anything else the
# build needed, never reaches the image that runs: less to download, less to attack.

# --- stage 1: build the virtual environment ---
FROM python:3.13-slim AS build

# uv, copied from its official image (same version as on your computer).
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /bin/uv

WORKDIR /app

# Packages first: this layer is rebuilt only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# --- stage 2: what runs ---
FROM python:3.13-slim

WORKDIR /app

# The packages from stage 1 (the same base image, so the same Python path), then the code.
COPY --from=build /app/.venv /app/.venv
COPY . .

# Use the packages in .venv directly.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Run as a user with no rights, not as root. The code and packages stay owned by root, so
# the service cannot change them; it may write only to /data (the worker's database).
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app /data
USER app

EXPOSE 8000
# Docker asks every 5 s: is the service ready? 3 failures in a row mark it "unhealthy".
HEALTHCHECK --interval=5s --timeout=4s --start-period=20s --retries=3 \
    CMD ["python", "-m", "agent.healthcheck"]
# 0.0.0.0: accept connections from outside the container, not only from inside it.
CMD ["uvicorn", "agent.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
