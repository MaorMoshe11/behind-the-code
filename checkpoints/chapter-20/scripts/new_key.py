"""Make an API key for one client of my-agent.

    uv run python scripts/new_key.py dana

Prints the key (give it to the client once; it is not saved anywhere) and the line the
server keeps instead: name:sha256-of-the-key, for AGENT_API_KEYS. To revoke a client,
remove its line and restart the api. To rotate, give the client a new key, keep both lines
until the client has switched, then remove the old one.
"""

import argparse
import hashlib
import re
import secrets
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Make an API key for one client.")
    parser.add_argument("name", help="the client's name: lowercase letters, digits, . _ -")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", args.name):
        sys.exit(f"Bad name {args.name!r}: use lowercase letters, digits, '.', '_' or '-'.")
    key = secrets.token_urlsafe(32)  # 256 random bits: nobody guesses this
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    print(f"Key for {args.name} (shown once, give it to them privately):")
    print(f"  {key}")
    print("Add this entry to AGENT_API_KEYS (comma separated), then restart the api:")
    print(f"  {args.name}:{digest}")


if __name__ == "__main__":
    main()
