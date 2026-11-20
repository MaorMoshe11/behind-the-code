"""The daily usage report: a batch job. Read one day of messages, write one CSV file.

    uv run python -m pipelines.usage_report                     # yesterday (UTC)
    uv run python -m pipelines.usage_report --day 2026-11-18    # any day: a backfill

The same two functions are the tasks of dags/daily_usage_report.py. They do not import
`agent`: a scheduler runs them on its own machines, with only what they need.
"""

import argparse
import csv
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, bindparam, create_engine, text

DAY_QUERY = text(
    """
    SELECT conversation_id,
           SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS turns,
           SUM(LENGTH(content)) AS chars
    FROM messages
    WHERE created_at >= :start AND created_at < :end
    GROUP BY conversation_id
    ORDER BY turns DESC, conversation_id
    """
).bindparams(bindparam("start", type_=DateTime()), bindparam("end", type_=DateTime()))


def extract(database_url: str, day: date) -> list[dict[str, Any]]:
    """One row per conversation that had messages on `day` (UTC). Reads only; changes nothing."""
    start = datetime.combine(day, time())  # the table stores UTC without a time zone
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            result = connection.execute(DAY_QUERY, {"start": start, "end": start + timedelta(1)})
            return [dict(row._mapping) for row in result]
    finally:
        engine.dispose()


def write_report(rows: list[dict[str, Any]], day: date, folder: Path) -> Path:
    """Write reports/usage-<day>.csv. Run it twice for one day: the same file, not two."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"usage-{day.isoformat()}.csv"
    partial = target.with_suffix(".tmp")  # write aside, then swap: never a half-written report
    with partial.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["conversation_id", "turns", "chars"])
        writer.writeheader()
        writer.writerows(rows)
    partial.replace(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the usage report of one day.")
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    parser.add_argument("--day", type=date.fromisoformat, default=yesterday)
    parser.add_argument("--out", type=Path, default=Path("reports"))
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL", "sqlite:///agent.db")
    rows = extract(url, args.day)
    path = write_report(rows, args.day, args.out)
    print(f"wrote {path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
