"""A tiny local HTTP server that prints every request it receives.

Point the agent at it to see exactly what the Anthropic SDK sends:

    uv run python scripts/echo_server.py
    $env:ANTHROPIC_BASE_URL = "http://127.0.0.1:8000"

POST /v1/messages gets a fake reply in the shape of the Messages API, so the
real ClaudeClient works against this server: offline, free, no real key needed.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# Headers that carry secrets: print only their first characters.
SECRET_HEADERS = {"authorization", "x-api-key"}


def hide_secret(value: str) -> str:
    """'Bearer sk-ant-abc123' -> 'Bearer sk-a***'."""
    scheme, _, token = value.rpartition(" ")
    return f"{scheme} {token[:4]}***".strip()


def fake_message(request: dict[str, object]) -> dict[str, object]:
    """A reply shaped like the Messages API's, so the SDK can read it."""
    messages = request.get("messages", [])
    count = len(messages) if isinstance(messages, list) else 0
    return {
        "id": "msg_echo",
        "type": "message",
        "role": "assistant",
        "model": request.get("model", "unknown"),
        "content": [{"type": "text", "text": f"[echo server] messages received: {count}"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},  # fake counts
    }


def fake_error(status: int) -> dict[str, object]:
    """An error body shaped like the API's, e.g. for 401, 429, 500 or 529."""
    return {
        "type": "error",
        "error": {"type": "api_error", "message": f"echo server answered {status} on purpose"},
    }


class EchoHandler(BaseHTTPRequestHandler):
    """Called by HTTPServer once for every request that arrives."""

    # Set from --status: answer every request with this status instead of 200.
    forced_status = 200

    def do_GET(self) -> None:
        self.answer()

    def do_POST(self) -> None:
        self.answer()

    def answer(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.print_request(body)

        if self.forced_status != 200:
            self.send_json(self.forced_status, fake_error(self.forced_status))
        elif self.command == "POST" and self.path == "/v1/messages":
            self.send_json(200, fake_message(json.loads(body)))
        else:
            self.send_json(200, {"method": self.command, "path": self.path, "bytes": length})

    def print_request(self, body: bytes) -> None:
        print(f"\n--- {self.requestline}")
        for name, value in self.headers.items():
            if name.lower() in SECRET_HEADERS:
                value = hide_secret(value)
            print(f"{name}: {value}")
        if body:
            print()
            print(body.decode("utf-8"))

    def send_json(self, status: int, data: dict[str, object]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print every HTTP request it receives.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--status", type=int, default=200, help="answer every request with it")
    args = parser.parse_args()
    EchoHandler.forced_status = args.status

    # 127.0.0.1: only programs on this computer can connect, not the network.
    server = HTTPServer(("127.0.0.1", args.port), EchoHandler)
    print(f"Echo server on http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
