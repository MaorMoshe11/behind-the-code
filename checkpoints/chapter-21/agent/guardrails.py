"""Guardrails: ordinary code that checks what goes into the model and what comes out.

A guardrail is not a prompt ("please never ..."). It is a check our code runs, the same way
every time, before or after the model: the model cannot talk its way past it. It catches
only what it was written for. The others in this project: tool input validation (chapter 18),
the limits on steps, tokens, time and rate (chapters 14, 16, 20), source checking of
subagent reports (chapter 20), and approval for writes (agent/approvals.py).
"""

import logging
import re

from agent.metrics import GUARDRAIL_BLOCKS

log = logging.getLogger(__name__)

# What a secret looks like: an Anthropic key, a GitHub token, a private key block. A message
# with one of these goes nowhere: not to the model, not to the database, not to the logs.
SECRET = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
REMOVED = "[removed: it looked like a secret]"


class Blocked(Exception):
    """The message was stopped by a guardrail. The text says why, for the user."""


def check_input(text: str) -> None:
    """Before anything else: refuse a message that carries a secret."""
    if SECRET.search(text):
        GUARDRAIL_BLOCKS.labels("secret_in").inc()
        log.warning("message blocked: it looks like it contains a secret")  # never the text
        raise Blocked(
            "That message looks like it contains a secret key, so it was not sent or saved. "
            "Remove the key (and, if it is real, revoke it) and send the message again."
        )


def check_output(reply: str) -> str:
    """After the model: never show or store something that looks like a secret. A model can
    repeat one it read in a note or a tool result."""
    cleaned = SECRET.sub(REMOVED, reply)
    if cleaned != reply:
        GUARDRAIL_BLOCKS.labels("secret_out").inc()
        log.warning("secret removed from a reply")
    return cleaned
