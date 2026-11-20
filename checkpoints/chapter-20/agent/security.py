"""Who may call the API, and how often.

Every client has its own key. The server keeps only a hash of each key (AGENT_API_KEYS),
so a leaked settings file or backup does not leak working keys. A key is a long random
string, so one SHA-256 is enough: slow hashes (bcrypt, argon2) are for passwords people
choose, which are short enough to guess.
"""

import hashlib
import math
import re
import time
from collections.abc import Callable

# The client of a single-key setup (AGENT_API_KEY) and of the terminal chat.
DEFAULT_CLIENT = "default"
CLIENT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def hash_key(key: str) -> str:
    """The SHA-256 of a key, as 64 hex characters: what the server stores instead of the key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def parse_clients(text: str) -> dict[str, str]:
    """AGENT_API_KEYS: "name:sha256" entries, separated by commas or new lines.

    Returns {hash: name}. A bad entry raises ValueError, naming the entry but never a key.
    """
    clients: dict[str, str] = {}
    for entry in re.split(r"[,\n]", text):
        entry = entry.strip()
        if not entry or entry.startswith("#"):
            continue
        name, _, digest = entry.partition(":")
        if not CLIENT_NAME.fullmatch(name) or not SHA256_HEX.fullmatch(digest):
            raise ValueError(f"bad entry {name!r}: expected name:<64 hex characters>")
        clients[digest] = name
    return clients


class RateLimiter:
    """At most `limit` requests per client in every window of `window` seconds.

    A fixed window: simple, and it lives in this process only. Two copies of the api
    would each allow `limit`; a shared limit needs a shared counter (Redis) or the edge.
    """

    def __init__(
        self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window
        self.clock = clock
        self.counts: dict[str, tuple[float, int]] = {}  # client -> (window start, requests)

    def check(self, client: str) -> int | None:
        """Count one request. None: allowed. A number: refused, retry after that many seconds."""
        now = self.clock()
        start, count = self.counts.get(client, (now, 0))
        if now - start >= self.window:
            start, count = now, 0  # a new window begins
        if count >= self.limit:
            return max(1, math.ceil(start + self.window - now))
        self.counts[client] = (start, count + 1)
        return None
