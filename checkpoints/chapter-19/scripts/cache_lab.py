"""A small cache in front of a slow source: what it saves, and when it lies.

Run it with: uv run python scripts/cache_lab.py
The "slow source" stands in for anything expensive: a paid model call, a heavy query.
"""

import time

# The source of truth. In real life: a database table, or a call to the model.
SOURCE = {"opening hours": "Sunday to Thursday, 9:00 to 17:00"}
SOURCE_DELAY = 0.2  # seconds: what one real answer costs us


def slow_answer(question: str) -> str:
    """Ask the source. Always correct, always slow."""
    time.sleep(SOURCE_DELAY)
    return SOURCE[question]


class TTLCache:
    """Keeps each value for `ttl` seconds, then forgets it."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.hits = 0
        self.misses = 0
        self._items: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        item = self._items.get(key)
        if item is None or item[1] < time.monotonic():
            self.misses += 1
            return None
        self.hits += 1
        return item[0]

    def set(self, key: str, value: str) -> None:
        self._items[key] = (value, time.monotonic() + self.ttl)

    def delete(self, key: str) -> None:
        self._items.pop(key, None)


def cached_answer(cache: TTLCache, question: str) -> str:
    """Cache-aside: look in the cache first, go to the source only on a miss."""
    answer = cache.get(question)
    if answer is None:
        answer = slow_answer(question)
        cache.set(question, answer)
    return answer


def timed(label: str, cache: TTLCache | None, question: str) -> None:
    start = time.perf_counter()
    answer = slow_answer(question) if cache is None else cached_answer(cache, question)
    print(f"{label}: {(time.perf_counter() - start) * 1000:7.2f} ms  {answer}")


def main() -> None:
    question = "opening hours"

    print("1. Without a cache, every question pays the full price")
    for i in range(3):
        timed(f"   call {i + 1}", None, question)

    print("2. With a cache, only the first one does")
    cache = TTLCache(ttl=1.0)
    for i in range(3):
        timed(f"   call {i + 1}", cache, question)
    print(f"   hits: {cache.hits}, misses: {cache.misses}")

    print("3. The source changes, and the cache does not know")
    SOURCE[question] = "Sunday to Thursday, 8:00 to 16:00"
    timed("   cached", cache, question)

    print("4. Fix A: wait for the TTL to pass")
    time.sleep(1.1)
    timed("   cached", cache, question)

    print("5. Fix B: whoever changes the source also deletes the key")
    SOURCE[question] = "Sunday to Thursday, 8:00 to 16:00, Friday 9:00 to 12:00"
    cache.delete(question)
    timed("   cached", cache, question)


if __name__ == "__main__":
    main()
