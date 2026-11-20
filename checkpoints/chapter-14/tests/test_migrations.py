"""The migrations must build exactly the tables that the code describes, and undo cleanly.

They run on a SQLite file every time. To run them on Postgres too, point TEST_DATABASE_URL
at an empty Postgres database (they delete every table in it):
    $env:TEST_DATABASE_URL = "postgresql+psycopg://agent:agent@127.0.0.1:5432/agent_test"
"""

import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from agent.db import Base, alembic_config, upgrade


@pytest.fixture(params=["sqlite", "postgres"])
def url(request, tmp_path):
    """Each test runs once per database: a new SQLite file, and Postgres when it is given."""
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'test.db'}"
        return
    postgres = os.getenv("TEST_DATABASE_URL")
    if not postgres:
        pytest.skip("TEST_DATABASE_URL is not set")
    yield postgres
    command.downgrade(alembic_config(postgres), "base")  # leave it empty for the next test


def differences(url):
    """What autogenerate would still write: the gap between the database and the classes."""
    engine = create_engine(url)
    with engine.connect() as connection:
        found = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    return found


def table_names(url):
    engine = create_engine(url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    return names


def test_the_migrations_build_the_tables_of_the_code(url):
    upgrade(url)
    assert differences(url) == []


def test_every_migration_can_be_undone(url):
    upgrade(url)
    command.downgrade(alembic_config(url), "base")  # every downgrade(), newest first
    assert table_names(url) == {"alembic_version"}
    upgrade(url)  # and up again, on a database that has been down
    assert differences(url) == []


def test_the_backfill_names_old_conversations(url):
    upgrade(url, "0001")  # the tables as they were in chapter 6, before titles
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversations (id, created_at) VALUES "
                "('chat', '2026-11-18 10:00'), ('empty', '2026-11-18 11:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES "
                "('chat', 'user', :first, '2026-11-18 10:00'), "
                "('chat', 'assistant', 'a reply', '2026-11-18 10:00'), "
                "('chat', 'user', 'the second question', '2026-11-18 10:01')"
            ),
            {"first": "a very long first question " * 3},
        )
    engine.dispose()

    upgrade(url)  # 0002 and 0003 run on rows that were already there
    engine = create_engine(url)
    with engine.connect() as connection:
        titles = dict(connection.execute(text("SELECT id, title FROM conversations")).all())
    engine.dispose()
    assert titles == {"chat": ("a very long first question " * 3)[:50], "empty": "New conversation"}


def test_old_conversations_belong_to_the_default_client(url):
    upgrade(url, "0006")  # before conversations had owners
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversations (id, title, created_at, user_id) VALUES "
                "('old', 'Old', '2026-11-18 10:00', NULL), "
                "('mine', 'Mine', '2026-11-18 11:00', 'dana')"
            )
        )
    engine.dispose()

    upgrade(url)  # 0007: every conversation without an owner gets the default client
    engine = create_engine(url)
    with engine.connect() as connection:
        owners = dict(connection.execute(text("SELECT id, user_id FROM conversations")).all())
    engine.dispose()
    assert owners == {"old": "default", "mine": "dana"}
