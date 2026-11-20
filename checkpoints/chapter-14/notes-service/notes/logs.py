"""Structured logs, as in the chat service: copied, like read_secret (a contract, not a library).

A person reads a log line once; a program searches millions of them. JSON lines can be
filtered by field ("every line of request 9f3c..."), counted and graphed, and a log
aggregator understands them without guessing.
"""

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

# The id of the request being handled right now, or None outside a request. A ContextVar
# is per request: two requests handled at the same time each see their own id.
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# An id that arrives from outside is only accepted if it looks like an id: it ends up in
# our logs, so a client must not be able to write anything it likes into them.
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

# The attributes every LogRecord has. Anything else on a record came from `extra=`.
STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}
STANDARD.add("color_message")  # uvicorn's copy of the message, with terminal colours


def new_request_id(incoming: str | None = None) -> str:
    """Keep a well-formed id that a caller sent (X-Request-ID); otherwise make a new one."""
    if incoming and SAFE_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class JsonFormatter(logging.Formatter):
    """Formats a record as one line of JSON."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        current = request_id.get()
        if current:
            line["request_id"] = current
        # Fields given with extra={...}: duration_ms, status, conversation_id, ...
        line.update({k: v for k, v in vars(record).items() if k not in STANDARD})
        if record.exc_info:
            # The whole traceback stays inside this one line, so it cannot get mixed up
            # with the lines of another request.
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)


def setup_logging(level: str, service: str, filename: str | None = None) -> None:
    """Send every log record, as JSON, to standard output (or to a file: the terminal chat).

    A service writes to stdout and nothing else. Collecting, storing and searching the
    lines is the platform's job (Docker, Kubernetes, a log aggregator), not the code's.
    """
    handler: logging.Handler
    if filename:
        handler = logging.FileHandler(filename, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn has handlers of its own, in plain text. Send its lines through ours instead.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    # Our middleware writes a better access line (with the request id and the duration).
    logging.getLogger("uvicorn.access").disabled = True
