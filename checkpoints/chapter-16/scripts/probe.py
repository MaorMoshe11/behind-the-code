"""Find out at which step a request to a URL fails: DNS, connection, or HTTP.

Run it with: uv run python scripts/probe.py http://127.0.0.1:8000/
"""

import socket
import sys
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit


def probe(url: str) -> bool:
    """Walk the steps one by one and stop at the first that fails."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"

    print(f"1. DNS      {host}")
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        print(f"   FAILED   the name does not resolve: {error}")
        return False
    print(f"   ok       {', '.join(str(info[4][0]) for info in found)}")

    print(f"2. CONNECT port {port}")
    try:
        socket.create_connection((host, port), timeout=5).close()
    except OSError as error:
        print(f"   FAILED   nobody answers on this port: {error}")
        return False
    print("   ok")

    step = "TLS + HTTP" if parts.scheme == "https" else "HTTP"
    print(f"3. {step}  GET {path}")
    connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    connection = connection_type(host, port, timeout=10)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
    except OSError as error:
        print(f"   FAILED   {error}")
        return False
    finally:
        connection.close()
    print(f"   answer   {response.status} {response.reason}")
    return response.status < 400


if __name__ == "__main__":
    sys.exit(0 if probe(sys.argv[1]) else 1)
