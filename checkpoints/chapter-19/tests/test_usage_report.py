"""The daily report's tasks, run as plain Python: no Airflow needed to test them."""

import py_compile
from datetime import UTC, datetime, timedelta

from agent.conversations import Conversations
from agent.db import make_engine, upgrade
from agent.llm import MockClient
from pipelines.usage_report import extract, write_report


def test_one_day_of_messages_becomes_one_report(tmp_path):
    url = f"sqlite:///{tmp_path / 'agent.db'}"
    upgrade(url)
    conversations = Conversations(MockClient(), 10, make_engine(url))
    busy, quiet = conversations.start(), conversations.start()
    conversations.send(busy, "one")
    conversations.send(busy, "two")
    conversations.send(quiet, "hi")
    today = datetime.now(UTC).date()
    rows = extract(url, today)
    assert [(row["conversation_id"], row["turns"]) for row in rows] == [(busy, 2), (quiet, 1)]
    assert extract(url, today - timedelta(days=1)) == []  # another day: nothing


def test_running_a_day_twice_gives_the_same_single_file(tmp_path):
    day = datetime(2026, 11, 17).date()
    rows = [{"conversation_id": "c1", "turns": 2, "chars": 80}]
    first = write_report(rows, day, tmp_path).read_text()
    second = write_report(rows, day, tmp_path).read_text()
    assert first == second
    assert [path.name for path in tmp_path.iterdir()] == ["usage-2026-11-17.csv"]


def test_the_dag_file_compiles():
    py_compile.compile("dags/daily_usage_report.py", doraise=True)  # Airflow itself is not here
