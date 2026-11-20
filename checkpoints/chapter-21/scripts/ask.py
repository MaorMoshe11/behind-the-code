"""Ask the agent's HTTP API one question, from another program.

Run it with: uv run python scripts/ask.py "your message" [--conversation ID]

It reads AGENT_API_KEY (and AGENT_URL, default http://127.0.0.1:8000) from the
environment or from .env, like the server does.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv


def ask(url: str, key: str, message: str, conversation_id: str | None) -> dict[str, object]:
    """POST /chat and return the JSON reply. Raises urllib errors on failure."""
    body = json.dumps({"message": message, "conversation_id": conversation_id})
    request = urllib.request.Request(
        f"{url}/chat",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    # Always a timeout: without one, a server that never answers blocks us forever.
    with urllib.request.urlopen(request, timeout=30) as response:
        reply: dict[str, object] = json.load(response)
        reply["request_id"] = response.headers.get("X-Request-ID")  # for finding it in logs
        return reply


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Send one message to the agent's API.")
    parser.add_argument("message")
    parser.add_argument("--conversation", help="continue this conversation id")
    args = parser.parse_args()

    url = os.getenv("AGENT_URL", "http://127.0.0.1:8000")
    key = os.getenv("AGENT_API_KEY")
    if not key:
        sys.exit("AGENT_API_KEY is not set.")

    try:
        data = ask(url, key, args.message, args.conversation)
    except urllib.error.HTTPError as error:
        # The server answered, with an error status (4xx or 5xx). Its body usually says why
        # in JSON; a crash inside the server (500) answers in plain text.
        body = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail")
        except json.JSONDecodeError:
            detail = body
        # The request id is what someone needs to find this failure in the logs.
        request_id = error.headers.get("X-Request-ID")
        sys.exit(f"The API answered {error.code}: {detail} (request {request_id})")
    except urllib.error.URLError as error:
        # No answer at all: DNS or connection failed (chapter 4).
        sys.exit(f"Could not reach {url}: {error.reason}")

    print(data["reply"])
    print(
        f"(conversation {data['conversation_id']}, turns: {data['turns']}, "
        f"request {data['request_id']})"
    )


if __name__ == "__main__":
    main()
