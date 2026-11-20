"""The alert rules: every alert is complete, and watches metrics that really exist.

An alert with a typo in a metric name never fires, and nothing tells you so. Prometheus
accepts it, because a metric may simply not exist yet. These tests catch it.
"""

import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agent.api import create_app
from agent.config import Settings
from agent.llm import MockClient

ROOT = Path(__file__).parent.parent
RULES = yaml.safe_load((ROOT / "monitoring" / "alerts.yml").read_text(encoding="utf-8"))
ALERTS = [rule for group in RULES["groups"] for rule in group["rules"]]
# Metrics that come from Prometheus itself or from the worker's process.
NOT_FROM_THE_API = {"up", "worker_consumer_lag"}


def test_every_alert_has_a_severity_and_a_runbook_entry():
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    headings = {line[3:].strip().lower() for line in runbook.splitlines() if line[:3] == "## "}
    for alert in ALERTS:
        assert alert["labels"]["severity"] in ("page", "ticket"), alert["alert"]
        anchor = alert["annotations"]["runbook_url"].split("#")[1]
        assert anchor == alert["alert"].lower()
        assert anchor in headings, f"docs/runbook.md has no section for {alert['alert']}"


def test_alerts_use_metrics_that_exist():
    settings = Settings(
        model="m", mock=True, agent_name="a", max_turns=2, api_key=None, agent_api_key="k"
    )
    page = TestClient(create_app(settings, MockClient())).get("/metrics").text
    # A metric family is announced by "# TYPE <name> <kind>", even before its first value.
    known = set(re.findall(r"^# TYPE (\w+) ", page, re.MULTILINE))
    known |= {f"{name}_total" for name in known} | {f"{name}_bucket" for name in known}
    for alert in ALERTS:
        names = set(re.findall(r"\b([a-z_]+)(?=\{|\[|\)| ==)", alert["expr"])) - {"by", "le"}
        missing = names - known - NOT_FROM_THE_API
        assert not missing, f"{alert['alert']} uses unknown metrics: {missing}"
