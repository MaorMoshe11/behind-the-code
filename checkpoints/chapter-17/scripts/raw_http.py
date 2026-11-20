"""Send one HTTP request by hand, as plain text over a TCP connection.

Run it with: uv run python scripts/raw_http.py 127.0.0.1 8000
"""

import socket
import sys

# The whole request. Every line ends with \r\n.
REQUEST = (
    "GET / HTTP/1.1\r\n"  # the request line: method, path, protocol version
    "Host: 127.0.0.1\r\n"  # headers, one per line
    "Connection: close\r\n"
    "\r\n"  # an empty line: the headers are over (a GET has no body)
)


def main() -> None:
    host, port = sys.argv[1], int(sys.argv[2])
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.sendall(REQUEST.encode("ascii"))
        reply = b""
        while chunk := connection.recv(4096):  # read until the server closes
            reply += chunk
    print(reply.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
