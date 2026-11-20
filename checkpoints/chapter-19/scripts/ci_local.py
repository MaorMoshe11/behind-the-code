"""Run the commands of a GitHub Actions workflow on this computer, in the same order as CI.

    uv run --locked python scripts/ci_local.py         # every job of .github/workflows/ci.yml
    uv run --locked python scripts/ci_local.py --job image  # one job, by its id in the file

Only `run:` steps run here. `uses:` steps (checkout, setup-uv) prepare GitHub's machine;
on yours, the project folder and your own uv play their part. Services (Postgres) are not
started: start them first (see README). Like CI, it stops at the first step that fails.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

DEFAULT_WORKFLOW = Path(".github/workflows/ci.yml")


def run_job(job_id: str, job: dict[str, Any]) -> None:
    """Run the steps of one job; exit with the step's exit code if one fails."""
    print(f"=== job {job_id}: {job.get('name', job_id)}", flush=True)
    if "services" in job:
        print(f"    services, not started here: {', '.join(job['services'])}", flush=True)
    job_env = {name: str(value) for name, value in job.get("env", {}).items()}
    # Where the steps run: defaults.run.working-directory of the job, or of one step.
    job_dir = job.get("defaults", {}).get("run", {}).get("working-directory", ".")
    for number, step in enumerate(job["steps"], start=1):
        title = step.get("name") or step.get("uses") or step.get("run")
        if "run" not in step:
            print(f"--- step {number}: {title} (skipped: GitHub only)", flush=True)
            continue
        folder = step.get("working-directory", job_dir)
        print(f"--- step {number}: {title}\n    {folder}$ {step['run']}", flush=True)
        step_env = {name: str(value) for name, value in step.get("env", {}).items()}
        started = time.monotonic()
        environment = {**os.environ, **job_env, **step_env}
        result = subprocess.run(step["run"], shell=True, env=environment, cwd=folder)
        if result.returncode != 0:
            print(
                f"FAILED: step {number} of job {job_id} ended with exit code "
                f"{result.returncode}. The steps after it did not run.",
                flush=True,
            )
            sys.exit(result.returncode)
        print(f"    ok ({time.monotonic() - started:.1f}s)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a workflow's commands locally.")
    parser.add_argument("workflow", nargs="?", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--job", help="run only this job")
    args = parser.parse_args()
    workflow = yaml.safe_load(args.workflow.read_text(encoding="utf-8"))
    jobs: dict[str, dict[str, Any]] = workflow["jobs"]
    if args.job and args.job not in jobs:
        sys.exit(f"No job {args.job!r}. The jobs are: {', '.join(jobs)}")
    for job_id, job in jobs.items():
        if args.job in (None, job_id):
            run_job(job_id, job)
    print("All steps passed.")


if __name__ == "__main__":
    main()
