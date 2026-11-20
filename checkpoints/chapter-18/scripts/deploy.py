"""Deploy one environment of my-agent on this computer, and check that it works.

    uv run python scripts/deploy.py staging
    uv run python scripts/deploy.py prod --skip-migrations   # a rollback: see README

The version is IMAGE_TAG in deploy/<environment>.env; the image my-agent:<IMAGE_TAG> must
exist. The steps: run the migrations with that image, start the containers and wait until
they are healthy, check that /ready reports that version, and send one chat (a smoke test).
It stops at the first step that fails, with exit code 1.
"""

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

DEPLOY = Path("deploy")


def read_env_file(path: Path) -> dict[str, str]:
    """The KEY=VALUE lines of an env file. Comments and empty lines are skipped."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def run(command: list[str]) -> None:
    print("    $ " + " ".join(command), flush=True)
    if subprocess.run(command).returncode != 0:
        sys.exit("FAILED. The steps after it did not run.")


def call(method: str, url: str, key: str = "", body: Any = None) -> Any:
    """One HTTP request; the JSON reply. A status of 400 or more raises HTTPError."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-API-Key": key}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read()
        return json.loads(text) if text else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy one environment and check it.")
    parser.add_argument("environment", choices=["staging", "prod"])
    parser.add_argument("--skip-migrations", action="store_true", help="for a rollback")
    args = parser.parse_args()
    env_file = DEPLOY / f"{args.environment}.env"
    config = read_env_file(env_file)
    version, base = config["IMAGE_TAG"], f"http://127.0.0.1:{config['API_PORT']}"
    compose = ["docker", "compose", "-p", f"my-agent-{args.environment}"]
    compose += ["-f", str(DEPLOY / "compose.yaml"), "--env-file", str(env_file)]

    print(f"=== deploy my-agent:{version} to {args.environment}", flush=True)
    if args.skip_migrations:
        print("--- 1. migrations: skipped", flush=True)
    else:
        print("--- 1. migrations, with the new image", flush=True)
        run([*compose, "run", "--rm", "migrate"])
    print("--- 2. start the new containers, and wait until they are healthy", flush=True)
    run([*compose, "up", "-d", "--wait", "--wait-timeout", "120"])
    try:
        print("--- 3. /ready reports the new version", flush=True)
        ready = call("GET", f"{base}/ready")
        print(f"    {ready}", flush=True)
        if ready["version"] != version:
            sys.exit(f"FAILED: {args.environment} runs {ready['version']}, not {version}.")
        # The chat would work without notes, so /ready says 200 anyway: check them here.
        if ready.get("notes") != "ok":
            sys.exit(f"FAILED: the api cannot reach the notes service ({ready.get('notes')}).")
        print("--- 4. smoke test: one message, then delete the conversation", flush=True)
        key = (DEPLOY / "secrets" / args.environment / "deploy_key.txt").read_text().strip()
        reply = call("POST", f"{base}/chat", key, {"message": "smoke test"})
        call("DELETE", f"{base}/conversations/{reply['conversation_id']}", key)
        print(f"    ok: {reply['reply']}", flush=True)
    except OSError as error:  # urllib's errors: no answer, or an error status
        sys.exit(f"FAILED: {error}")
    print(f"{args.environment} runs my-agent:{version}.")


if __name__ == "__main__":
    main()
