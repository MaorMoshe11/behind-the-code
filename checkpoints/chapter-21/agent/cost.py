"""Tokens to money: what each model call costs, by the prices in agent/prices.toml.

The API bills four kinds of tokens at four prices. The usage of every response says how many
of each it used; this module turns them into dollars, so the metrics, the logs and the traces
can say what a message, a conversation or a client costs.
"""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
PRICES_FILE = Path(__file__).with_name("prices.toml")
MILLION = 1_000_000


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens of each kind."""

    input: float
    cache_write: float
    cache_read: float
    output: float


def load_prices(path: Path = PRICES_FILE) -> tuple[str, dict[str, Price]]:
    """(the date the prices were checked, {model: price})."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    prices = {model: Price(**values) for model, values in data["models"].items()}
    return str(data["checked"]), prices


CHECKED, PRICES = load_prices()
_unknown: set[str] = set()  # models we warned about once


def dollars(model: str, input: int, cache_read: int, cache_write: int, output: int) -> float:
    """What one call cost. A model with no price costs 0, with one warning in the log: a
    missing price must be visible, not a crash in the middle of a conversation."""
    price = PRICES.get(model)
    if price is None:
        if model not in _unknown:
            _unknown.add(model)
            log.warning("no price for model %s in prices.toml: counted as $0", model)
        return 0.0
    return (
        input * price.input
        + cache_read * price.cache_read
        + cache_write * price.cache_write
        + output * price.output
    ) / MILLION
