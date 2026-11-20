"""Create the secrets of one environment, as files that never enter git or the image.

    uv run python scripts/make_secrets.py staging

Writes deploy/secrets/<environment>/<name>.txt with a new random value, for every secret
that does not exist yet. An existing secret is never overwritten: delete its file first
(see README, "Rotating a secret"). On a real server a secrets manager plays this part.

The api never gets a key in plain text: deploy_key.txt (the key scripts/deploy.py uses for
its smoke test) stays on this computer, and api_clients.txt holds only its hash.
"""

import argparse
import hashlib
import secrets
from pathlib import Path

SECRETS = ("db_password", "deploy_key", "notes_db_password", "notes_api_key")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the missing secrets of an environment.")
    parser.add_argument("environment", choices=["staging", "prod"])
    args = parser.parse_args()
    folder = Path("deploy") / "secrets" / args.environment
    folder.mkdir(parents=True, exist_ok=True)
    for name in SECRETS:
        path = folder / f"{name}.txt"
        if path.exists():
            print(f"kept     {path}")
            continue
        # A random value, written with no newline (a stray "\r" would become part of it).
        path.write_text(secrets.token_urlsafe(24), encoding="ascii", newline="")
        print(f"created  {path}")
    # What the api keeps: the hash of the deploy key. Rewritten every time, so it always
    # matches deploy_key.txt; more clients go in AGENT_API_KEYS of a real secrets manager.
    key = (folder / "deploy_key.txt").read_text(encoding="ascii").strip()
    clients = folder / "api_clients.txt"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    clients.write_text(f"deploy:{digest}", encoding="ascii", newline="")
    print(f"wrote    {clients} (the hash of deploy_key.txt)")


if __name__ == "__main__":
    main()
