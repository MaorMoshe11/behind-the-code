"""SQL injection, shown harmlessly: a throwaway table in memory, gone when the script ends.

    uv run python scripts/injection_lab.py "Dana"
    uv run python scripts/injection_lab.py "x' OR '1'='1"

The same search, written twice: once by pasting the input into the SQL text, once with a
parameter. Only the first can be talked into returning rows it should not.
"""

import sqlite3
import sys


def make_db() -> sqlite3.Connection:
    """Three users, each with a private note. Only in memory."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE users (name TEXT, private_note TEXT)")
    db.executemany(
        "INSERT INTO users VALUES (?, ?)",
        [("Dana", "dentist on Tuesday"), ("Omer", "salary 21,000"), ("Noa", "new job soon")],
    )
    return db


def find_unsafe(db: sqlite3.Connection, name: str) -> list[tuple[str, str]]:
    """WRONG: the input becomes part of the SQL text, so it can change what the SQL says."""
    sql = f"SELECT name, private_note FROM users WHERE name = '{name}'"
    print(f"  SQL sent: {sql}")
    return db.execute(sql).fetchall()


def find_safe(db: sqlite3.Connection, name: str) -> list[tuple[str, str]]:
    """RIGHT: the SQL text is fixed; the input travels separately, as a value (a parameter)."""
    sql = "SELECT name, private_note FROM users WHERE name = ?"
    print(f"  SQL sent: {sql}   value: {name!r}")
    return db.execute(sql, (name,)).fetchall()


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "Dana"
    db = make_db()
    print("unsafe:")
    print(f"  rows: {find_unsafe(db, name)}")
    print("safe:")
    print(f"  rows: {find_safe(db, name)}")


if __name__ == "__main__":
    main()
