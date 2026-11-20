"""conversations belong to a client

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-18 23:27:47.719674

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

conversations = sa.table("conversations", sa.column("user_id", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_conversations_user_id"), ["user_id"], unique=False)
    # Every conversation from before had one possible owner: whoever held the single key.
    op.execute(
        conversations.update()
        .where(conversations.c.user_id.is_(None))
        .values(user_id=sa.literal("default", sa.String))
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The owners stay: the column existed before this migration, and older code ignores it.
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conversations_user_id"))
