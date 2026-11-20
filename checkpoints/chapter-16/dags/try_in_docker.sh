#!/usr/bin/env bash
# Try the DAG once, in a throwaway container, without installing Airflow on your computer.
# From the project folder, with `docker compose up -d db` running (see README, "Pipelines"):
#   docker run --rm --network my-agent_default -v "${PWD}:/project:ro" python:3.13-slim bash /project/dags/try_in_docker.sh
set -e
export PYTHONPATH=/project AIRFLOW_HOME=/tmp/airflow
export AIRFLOW__CORE__DAGS_FOLDER=/project/dags AIRFLOW__CORE__LOAD_EXAMPLES=False
export REPORT_DATABASE_URL=postgresql+psycopg://agent:agent@db:5432/agent REPORT_FOLDER=/tmp/reports
echo "installing Airflow (a few minutes)..."
pip install -q --root-user-action=ignore --disable-pip-version-check "apache-airflow==3.4.0" "psycopg[binary]" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.4.0/constraints-3.13.txt"
airflow db migrate > /tmp/migrate.log                 # Airflow's own database (SQLite, in /tmp)
airflow tasks list daily_usage_report 2>/dev/null     # the DAG parses: its tasks
airflow dags test daily_usage_report "${1:-2026-11-19}" 2>&1 | grep -E "Done. Returned|DagRun Finished"
cat /tmp/reports/*.csv
