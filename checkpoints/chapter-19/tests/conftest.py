"""Shared test setup. pytest loads this file by itself, before the tests."""

import pytest
from prometheus_client import REGISTRY


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    """Runs before every test: make sure no test can reach the real API by mistake."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


@pytest.fixture
def metric():
    """Read one metric's current value, as /metrics would show it (0 if never counted)."""

    def read(name, **labels):
        return REGISTRY.get_sample_value(name, labels) or 0

    return read
