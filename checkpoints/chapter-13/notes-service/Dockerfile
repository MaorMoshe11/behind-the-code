# The image of the notes service. Built from this folder only: docker build notes-service
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8100
# Ready means: the process answers and its database answers (GET /ready).
HEALTHCHECK --interval=5s --timeout=4s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/ready', timeout=3)"]
CMD ["uvicorn", "notes.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8100"]
