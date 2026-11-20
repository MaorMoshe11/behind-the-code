"""Airflow DAG: every night, the usage report of the day before.

Airflow is not a dependency of this project: this file runs inside an Airflow installation,
which must also have the `pipelines` package and SQLAlchemy (see README, "Pipelines").
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.sdk import dag, task

from pipelines import usage_report

DATABASE_URL = os.environ.get("REPORT_DATABASE_URL", "sqlite:///agent.db")
REPORTS = Path(os.environ.get("REPORT_FOLDER", "reports"))


def day_before(logical_date: datetime | None) -> date:
    """The run at 02:00 on the 19th reports on the 18th, a day that is over."""
    assert logical_date is not None  # Airflow passes it to every scheduled run
    return logical_date.date() - timedelta(days=1)


@dag(
    schedule="0 2 * * *",  # cron: every day at 02:00 UTC
    start_date=datetime(2026, 11, 1),  # no run is about anything earlier
    catchup=False,  # do not run every missed night at once; backfill on purpose
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["my-agent"],
)
def daily_usage_report() -> None:
    @task
    def extract(logical_date: datetime | None = None) -> list[dict[str, Any]]:
        # Airflow fills logical_date from the run (it is a name Airflow knows).
        return usage_report.extract(DATABASE_URL, day_before(logical_date))

    @task
    def write(rows: list[dict[str, Any]], logical_date: datetime | None = None) -> str:
        return str(usage_report.write_report(rows, day_before(logical_date), REPORTS))

    write(extract())  # extract runs first; its rows reach write through XCom


daily_usage_report()
