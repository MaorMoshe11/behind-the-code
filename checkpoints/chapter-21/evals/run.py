"""Run the agent evals: every case of evals/cases.json, graded, with a pass rate.

    uv run python -m evals.run --mock              # offline, free: what CI runs
    uv run python -m evals.run --repeat 5          # the model in .env, each case 5 times
    uv run python -m evals.run --mock --save evals/results/before.json
    uv run python -m evals.run --compare evals/results/before.json evals/results/after.json
    uv run python -m evals.run --judge             # also the rubrics (a model call each)
    uv run python -m evals.run --calibrate         # the judge against human labels

Against the mock, the evals check the harness: the tools, the loop's rules, the approvals,
the guardrails, the team's plumbing. The mock's answers are scripted, so a passing case says
nothing about how well a real model behaves; the same cases, run with CHAT_MOCK=0, do.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent import logs, tracing
from agent.approvals import Request
from agent.config import SYSTEM_PROMPT, Settings, load_settings
from agent.context import fingerprint
from agent.guardrails import Blocked
from agent.llm import AgentClient, ClaudeClient, LLMError, MockClient
from agent.notes_tools import TOOLS
from agent.team import ORCHESTRATOR_PROMPT
from evals.graders import JUDGE_PROMPT, Trajectory, grade, judge
from evals.world import World, build_world

HERE = Path(__file__).parent
CASES = HERE / "cases.json"
LABELS = HERE / "judge_labels.json"
TRACES = Path("traces") / "evals"  # failed runs keep their trace here (in .gitignore)

ClientFactory = Callable[[str, bool], AgentClient]  # (system prompt, main model?) -> client


@dataclass
class CaseResult:
    case: str
    runs: int = 0
    passed: int = 0
    failures: list[str] = field(default_factory=list)  # of the first failed run
    model_calls: int = 0
    tokens: int = 0
    cost: float = 0.0


def clients(settings: Settings, mock: bool) -> ClientFactory:
    """How each agent of a case gets its client: the mock, or the real model of .env."""

    def make(prompt: str, main: bool) -> AgentClient:
        if mock:
            return MockClient(prompt, model=settings.model)
        model = settings.model if main else settings.worker_model
        return ClaudeClient(
            model, prompt, effort=settings.effort, fallback_model=settings.fallback_model
        )

    return make


def scripted(answer: str, world: World) -> Callable[[Request], bool]:
    """The person of the case: always answers the same, and we keep what they were shown."""

    def decide(request: Request) -> bool:
        world.approvals.append(request.text())
        return answer == "yes"

    return decide


def run_once(
    case: dict[str, Any],
    settings: Settings,
    make: ClientFactory,
    number: int,
) -> tuple[list[str], Trajectory]:
    """One run of one case in a new world: send its messages, then grade."""
    world = build_world(
        case.get("setup", {}),
        settings,
        make(SYSTEM_PROMPT, True),
        lambda prompt: make(prompt, prompt == ORCHESTRATOR_PROMPT),
    )
    request = logs.request_id.set(f"{case['id']}-{number}")
    try:
        with tracing.span(case["id"], "eval") as span:
            reply = ""
            for message in case["messages"]:
                approver = scripted(case.get("approve", "no"), world)
                try:
                    reply = world.conversations.send(world.conversation_id, message, approver)
                except Blocked as error:  # a guardrail's answer is the answer
                    reply = f"(blocked) {error}"
                except LLMError as error:
                    reply = f"(model call failed) {error}"
        run = Trajectory.of(span, reply)
        failures = grade(case["expect"], run, world)
        if failures:
            tracing.save(span, str(TRACES))  # a failed run can be opened and read
        return failures, run
    finally:
        logs.request_id.reset(request)


def run_cases(
    cases: list[dict[str, Any]], settings: Settings, make: ClientFactory, repeat: int
) -> list[CaseResult]:
    results = []
    for case in cases:
        result = CaseResult(case["id"])
        for number in range(1, repeat + 1):
            failures, run = run_once(case, settings, make, number)
            result.runs += 1
            result.passed += not failures
            result.model_calls += run.model_calls
            result.tokens += run.tokens
            result.cost += run.cost
            if failures and not result.failures:
                result.failures = failures
        results.append(result)
    return results


def report(results: list[CaseResult], mock: bool, version: str, seconds: float) -> dict[str, Any]:
    width = max(len(r.case) for r in results)
    print(f"{'case':<{width}}  runs  result")
    for r in results:
        verdict = "pass" if r.passed == r.runs else f"FAIL: {r.failures[0]}"
        print(f"{r.case:<{width}}  {r.passed}/{r.runs}   {verdict}")
    runs = sum(r.runs for r in results)
    passed = sum(r.passed for r in results)
    cases_ok = sum(r.passed == r.runs for r in results)
    cost = sum(r.cost for r in results)
    print(
        f"\ncases passed: {cases_ok}/{len(results)}, runs passed: {passed}/{runs} "
        f"({passed / runs:.0%}); model calls: {sum(r.model_calls for r in results)}, "
        f"tokens: {sum(r.tokens for r in results)}, cost: ${cost:.4f}"
        f"{' (the mock: made-up tokens at real prices)' if mock else ''}; "
        f"prompt {version}; {seconds:.1f} s"
    )
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "mock": mock,
        "prompt_version": version,
        "pass_rate": passed / runs,
        "cost_usd": round(cost, 6),
        "cases": {
            r.case: {"passed": r.passed, "runs": r.runs, "failures": r.failures} for r in results
        },
    }


def compare(old_path: Path, new_path: Path) -> None:
    """What changed between two saved runs, case by case."""
    old = json.loads(old_path.read_text(encoding="utf-8"))
    new = json.loads(new_path.read_text(encoding="utf-8"))
    print(
        f"prompt {old['prompt_version']} -> {new['prompt_version']}, pass rate "
        f"{old['pass_rate']:.0%} -> {new['pass_rate']:.0%}, cost ${old['cost_usd']:.4f} -> "
        f"${new['cost_usd']:.4f}"
    )
    for case in sorted(set(old["cases"]) | set(new["cases"])):
        a, b = old["cases"].get(case), new["cases"].get(case)
        if a is None or b is None:
            print(f"  {case}: {'new case' if a is None else 'removed'}")
            continue
        before, after = a["passed"] / a["runs"], b["passed"] / b["runs"]
        if after < before:
            print(
                f"  WORSE  {case}: {a['passed']}/{a['runs']} -> {b['passed']}/{b['runs']}  "
                f"{(b['failures'] or [''])[0]}"
            )
        elif after > before:
            print(f"  better {case}: {a['passed']}/{a['runs']} -> {b['passed']}/{b['runs']}")


def run_judge(cases: list[dict[str, Any]], settings: Settings, make: ClientFactory) -> None:
    """The rubric of every case that has one, graded by the judge on one fresh run."""
    grader = make(JUDGE_PROMPT, True)
    for case in [c for c in cases if "rubric" in c["expect"]]:
        _, run = run_once(case, settings, make, 1)
        ok, reason = judge(grader, case["expect"]["rubric"], case["messages"][-1], run.reply)
        print(f"{case['id']}: {'pass' if ok else 'FAIL'} ({reason})")


def calibrate(make: ClientFactory) -> None:
    """How often the judge agrees with a person, on answers the person already labelled."""
    grader = make(JUDGE_PROMPT, True)
    items = json.loads(LABELS.read_text(encoding="utf-8"))
    agree = 0
    for item in items:
        ok, reason = judge(grader, item["rubric"], item["question"], item["answer"])
        said = "pass" if ok else "fail"
        agree += said == item["human"]
        if said != item["human"]:
            print(f"DISAGREE {item['id']}: judge {said}, person {item['human']} ({reason})")
    print(f"the judge agrees with the person on {agree}/{len(items)} ({agree / len(items):.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__.split("\n")[0])
    parser.add_argument("--mock", action="store_true", help="use the mock, whatever .env says")
    parser.add_argument("--case", action="append", help="run only this case (repeatable)")
    parser.add_argument("--repeat", type=int, default=1, help="runs of each case")
    parser.add_argument("--save", type=Path, help="write the results as JSON")
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("OLD", "NEW"))
    parser.add_argument("--judge", action="store_true", help="grade the rubrics with the judge")
    parser.add_argument("--calibrate", action="store_true", help="the judge vs. human labels")
    parser.add_argument("--min-pass-rate", type=float, help="exit 1 below this (0 to 1)")
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
        return
    load_dotenv()
    settings = load_settings()
    mock = args.mock or settings.mock
    if not mock and not settings.api_key:
        print("ANTHROPIC_API_KEY is not set: run with --mock, or set the key (it costs money).")
        sys.exit(1)
    # The agent's log lines go to a file, so the report stays readable.
    logs.setup_logging("WARNING", "evals", filename="evals.log")
    make = clients(settings, mock)
    if args.calibrate:
        calibrate(make)
        return
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    if args.judge:
        run_judge(cases, settings, make)
        return
    started = time.perf_counter()
    results = run_cases(cases, settings, make, args.repeat)
    version = fingerprint(SYSTEM_PROMPT, [tool.param() for tool in TOOLS])
    summary = report(results, mock, version, time.perf_counter() - started)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if args.min_pass_rate is not None and summary["pass_rate"] < args.min_pass_rate:
        print(f"The pass rate is below {args.min_pass_rate:.0%}.")
        sys.exit(1)


if __name__ == "__main__":
    main()
