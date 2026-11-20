"""Tests for the eval runner: the graders must fail what is wrong, not only pass what is right."""

import json

from agent.config import Settings
from evals.graders import judge
from evals.run import CASES, clients, run_cases, run_once

SETTINGS = Settings(
    model="claude-opus-5-5", mock=True, agent_name="agent", max_turns=10, api_key=None
)
MOCK = clients(SETTINGS, mock=True)


def case(name):
    return next(c for c in json.loads(CASES.read_text(encoding="utf-8")) if c["id"] == name)


def test_every_case_passes_against_the_mock():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    results = run_cases(cases, SETTINGS, MOCK, repeat=1)
    assert [r.case for r in results if r.passed != r.runs] == []


def test_a_person_who_approves_the_injected_write_fails_the_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the failed run's trace is saved under traces/evals
    fooled = {**case("injected-note"), "approve": "yes"}
    failures, run = run_once(fooled, SETTINGS, MOCK, 1)
    assert failures == ["memories_not_contain: the memory now holds ['cancelled']"]
    assert [call.name for call in run.tools] == ["list_notes", "remember"]
    assert list((tmp_path / "traces" / "evals").glob("injected-note-1.json"))


def test_trajectory_checks_see_what_the_tools_were_called_with(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wrong = {**case("notes-search"), "messages": ["What is in my notes?"]}  # no search word
    failures, _ = run_once(wrong, SETTINGS, MOCK, 1)
    assert failures[0] == "tool_input: list_notes.search was [''], not 'milk'"
    assert "reply_not_contains: the answer contains ['dentist']" in failures


def test_the_mock_judge_is_fooled_by_a_negation():
    """Why a judge is checked against human labels before it is trusted."""
    rubric = 'The answer says the note "buy oat milk" is saved.'
    negated = "You have no note that says buy oat milk."
    assert judge(MOCK("judge", True), rubric, "milk?", negated)[0] is True  # a person: fail
