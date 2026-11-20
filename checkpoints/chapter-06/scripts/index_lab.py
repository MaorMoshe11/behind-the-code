"""How much does an index help? Times one query before and after CREATE INDEX.

Run it with: uv run python scripts/index_lab.py
Everything happens in an in-memory SQLite database, so no file is left behind.
"""

import sqlite3
import time

CONVERSATIONS = 10_000
MESSAGES_PER_CONVERSATION = 50
QUERY = "SELECT content FROM messages WHERE conversation_id = ? ORDER BY id"


def fill(db: sqlite3.Connection) -> None:
    """Create the messages table and fill it with fake messages."""
    db.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL,"
        " role TEXT NOT NULL, content TEXT NOT NULL)"
    )
    rows = (
        (f"c{c}", "user" if m % 2 == 0 else "assistant", f"message {m} of conversation {c}")
        for c in range(CONVERSATIONS)
        for m in range(MESSAGES_PER_CONVERSATION)
    )
    # The ? placeholders: the values travel separately from the SQL text.
    db.executemany("INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)", rows)
    db.commit()


def time_queries(db: sqlite3.Connection, label: str, repeats: int = 200) -> None:
    """Run the query for `repeats` different conversations and print the average time."""
    plan = db.execute("EXPLAIN QUERY PLAN " + QUERY, ("c1",)).fetchall()
    start = time.perf_counter()
    for i in range(repeats):
        db.execute(QUERY, (f"c{i * 37 % CONVERSATIONS}",)).fetchall()
    average_ms = (time.perf_counter() - start) / repeats * 1000
    print(f"{label}: {average_ms:.3f} ms per query  plan: {plan[0][3]}")


def main() -> None:
    db = sqlite3.connect(":memory:")
    fill(db)
    count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"{count:,} messages in {CONVERSATIONS:,} conversations")
    time_queries(db, "without index")
    start = time.perf_counter()
    db.execute("CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)")
    print(f"CREATE INDEX took {(time.perf_counter() - start) * 1000:.0f} ms")
    time_queries(db, "with index   ")
    db.close()


if __name__ == "__main__":
    main()
