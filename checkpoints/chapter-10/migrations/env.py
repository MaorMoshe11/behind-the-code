"""Alembic runs this file for every command. It says which database, and which tables."""

from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

from agent.config import database_url
from agent.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)  # the logging settings at the end of alembic.ini

# The tables as the code describes them. autogenerate compares the database to these.
target_metadata = Base.metadata

# Code that runs migrations (like the tests) passes the URL in; otherwise the same
# database as the agent: DATABASE_URL and its password, from the terminal or from .env.
load_dotenv()
url = config.attributes.get("url") or database_url()


def run_migrations_offline() -> None:
    """--sql: print the SQL instead of running it. No connection is made."""
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect, and run the migrations inside a transaction."""
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # render_as_batch: on SQLite, autogenerate writes changes that copy the table (7.7).
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
