"""Copy every conversation and message from one database into another, empty one.

For example, from the SQLite file into the Postgres of docker compose:
    uv run python scripts/copy_conversations.py sqlite:///agent.db \
        postgresql+psycopg://agent:agent@127.0.0.1:5432/agent
Both databases must be at the same migration (run `alembic upgrade head` on both first).
"""

import argparse
import sys

from sqlalchemy import Connection, MetaData, create_engine, func, insert, select, text


def revision(connection: Connection) -> str | None:
    """Where the database is in the migration chain."""
    found = connection.scalar(text("SELECT version_num FROM alembic_version"))
    return str(found) if found is not None else None


def copy(source_url: str, target_url: str) -> tuple[int, int]:
    """Copy the rows; return how many conversations and messages were copied."""
    source = create_engine(source_url)
    target = create_engine(target_url)
    tables = MetaData()
    tables.reflect(target, only=["conversations", "messages"])  # the tables as they really are
    conversations = tables.tables["conversations"]
    messages = tables.tables["messages"]

    with source.connect() as reading, target.begin() as writing:  # one transaction
        if revision(reading) != revision(writing):
            sys.exit("The databases are at different migrations. Run alembic upgrade head on both.")
        if writing.scalar(select(func.count()).select_from(conversations)):
            sys.exit("The target already has conversations. Copy only into an empty database.")
        conversation_rows = [dict(row._mapping) for row in reading.execute(select(conversations))]
        message_rows = [dict(row._mapping) for row in reading.execute(select(messages))]
        if conversation_rows:
            writing.execute(insert(conversations), conversation_rows)
        if message_rows:
            writing.execute(insert(messages), message_rows)
        if message_rows and writing.dialect.name == "postgresql":
            # Postgres numbers new messages from a sequence. The copied rows brought their own
            # ids and did not move it, so the next new message would get id 1 again.
            writing.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('messages', 'id'), MAX(id)) FROM messages"
                )
            )
    source.dispose()
    target.dispose()
    return len(conversation_rows), len(message_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy conversations between databases.")
    parser.add_argument("source", help="where to read, e.g. sqlite:///agent.db")
    parser.add_argument("target", help="where to write: migrated and empty")
    args = parser.parse_args()
    conversation_count, message_count = copy(args.source, args.target)
    print(f"Copied {conversation_count} conversations and {message_count} messages.")


if __name__ == "__main__":
    main()
