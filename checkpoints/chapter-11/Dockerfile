# The image of the agent's HTTP service: Python, the locked packages, and the code.
FROM python:3.13-slim

# uv, copied from its official image (same version as on your computer).
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /bin/uv

WORKDIR /app

# Packages first: this layer is rebuilt only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# Then the code, which changes often.
COPY . .

# Use the packages in .venv without `uv run` (which would also install the dev tools).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# Docker asks every 5 s: is the service ready? 3 failures in a row mark it "unhealthy".
HEALTHCHECK --interval=5s --timeout=4s --start-period=20s --retries=3 \
    CMD ["python", "-m", "agent.healthcheck"]
# 0.0.0.0: accept connections from outside the container, not only from inside it.
CMD ["uvicorn", "agent.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
