"""titles are cut after a whole word

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19 12:13:57.578756

"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The tables as they are at this revision, not as agent/db.py says today.
conversations = sa.table("conversations", sa.column("id", sa.String), sa.column("title", sa.String))
messages = sa.table(
    "messages",
    sa.column("id", sa.Integer),
    sa.column("conversation_id", sa.String),
    sa.column("role", sa.String),
    sa.column("content", sa.Text),
)
TITLE_LENGTH = 50
CUT = "..."
NEW_TITLE = "New conversation"


def make_title(text: str) -> str:
    """A copy of agent.conversations.make_title as it is at this revision (AGENT-42).

    A copy on purpose: this migration must keep doing the same thing after the code changes.
    """
    words = " ".join(text.split())
    if not words:
        return NEW_TITLE
    if len(words) <= TITLE_LENGTH:
        return words
    room = TITLE_LENGTH - len(CUT)
    space = words.rfind(" ", 0, room + 1)
    end = space if space > 0 else room
    return words[:end] + CUT


def old_title(text: str) -> str:
    """The rule before this revision: the first 50 characters, as they are."""
    return text[:TITLE_LENGTH]


def with_first_message() -> list[sa.Row[tuple[str, str, str]]]:
    """(id, title, first user message) of every conversation that has a message."""
    first = (
        sa.select(sa.func.min(messages.c.id))
        .where(messages.c.role == "user")
        .group_by(messages.c.conversation_id)
    )
    query = (
        sa.select(conversations.c.id, conversations.c.title, messages.c.content)
        .join(messages, messages.c.conversation_id == conversations.c.id)
        .where(messages.c.id.in_(first))
    )
    return list(op.get_bind().execute(query))


def retitle(rule_now: Callable[[str], str], rule_after: Callable[[str], str]) -> None:
    """Give a new title to every conversation whose title still follows rule_now."""
    if op.get_context().as_sql:  # --sql writes SQL without a database: there are no rows
        raise RuntimeError("0008 reads the conversations in Python; run it without --sql.")
    for conversation_id, title, first_message in with_first_message():
        # Any other title is kept: after /reset, the message it came from is gone.
        if title == rule_now(first_message) and title != rule_after(first_message):
            op.execute(
                conversations.update()
                .where(conversations.c.id == conversation_id)
                .values(title=rule_after(first_message))
            )


def upgrade() -> None:
    """Upgrade schema."""
    retitle(old_title, make_title)


def downgrade() -> None:
    """Downgrade schema."""
    retitle(make_title, old_title)
