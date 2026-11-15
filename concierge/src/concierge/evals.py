import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from concierge.interpreter import Interpretation, StartIntent

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"
CASES_FILE = EVALS_DIR / "interpreter.json"
START_CASES_FILE = EVALS_DIR / "start.json"


@dataclass(frozen=True)
class Case:
    name: str
    category: str
    key: str
    text: str
    questions: dict[int, str]
    expect: tuple[str, ...]
    forbid: tuple[str, ...]
    answers: dict[int, str]
    feedback_contains: str


@dataclass(frozen=True)
class StartCase:
    name: str
    category: str
    text: str
    repos: tuple[str, ...]
    expect: tuple[str, ...]
    repo: str | None
    forbid: tuple[str, ...]
    idea_contains: str


@dataclass(frozen=True)
class CaseResult:
    case: Case | StartCase
    failures: list[str]


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    return [
        Case(
            raw["name"], raw["category"], raw["key"], raw["text"], {int(n): q for n, q in raw.get("questions", {}).items()},
            tuple(raw.get("expect", ())), tuple(raw.get("forbid", ())), {int(n): a for n, a in raw.get("answers", {}).items()},
            raw.get("feedback_contains", ""),
        )
        for raw in json.loads(path.read_text())
    ]


def load_start_cases(path: Path = START_CASES_FILE) -> list[StartCase]:
    return [
        StartCase(
            raw["name"], raw["category"], raw["text"], tuple(raw.get("repos", ("shop", "blog"))), tuple(raw.get("expect", ())),
            raw.get("repo"), tuple(raw.get("forbid", ())), raw.get("idea_contains", ""),
        )
        for raw in json.loads(path.read_text())
    ]


def start_failures(case: StartCase, result: StartIntent) -> list[str]:
    found = []
    if case.expect and result.kind not in case.expect:
        found.append(f"expected {'/'.join(case.expect)}, got {result.kind}")
    if result.kind in case.forbid:
        found.append(f"must not be {result.kind}")
    if case.repo is not None and result.repo != case.repo:
        found.append(f"expected repo '{case.repo}', got '{result.repo}'")
    if case.idea_contains and case.idea_contains.lower() not in result.idea.lower():
        found.append(f"idea should mention '{case.idea_contains}', got '{result.idea}'")
    return found


def failures(case: Case, result: Interpretation) -> list[str]:
    found = []
    if case.expect and result.action not in case.expect:
        found.append(f"expected {'/'.join(case.expect)}, got {result.action}")
    if result.action in case.forbid:
        found.append(f"must not be {result.action}")
    if case.answers:
        got = {a.n: a.text for a in result.answers}
        if got.keys() != case.answers.keys() or any(case.answers[n].lower() not in got[n].lower() for n in got if n in case.answers):
            found.append(f"expected answers {case.answers}, got {got}")
    if any("/allow" in a.text for a in result.answers):
        found.append("an answer carries a /allow rule")
    if case.feedback_contains and case.feedback_contains.lower() not in result.feedback.lower():
        found.append(f"feedback should mention '{case.feedback_contains}', got '{result.feedback}'")
    return found


def run_cases(interpret: Callable[[Case], Interpretation], cases: list[Case] | None = None) -> list[CaseResult]:
    return [CaseResult(case, failures(case, interpret(case))) for case in cases or load_cases()]


def run_start_cases(intent: Callable[[StartCase], StartIntent], cases: list[StartCase] | None = None) -> list[CaseResult]:
    return [CaseResult(case, start_failures(case, intent(case))) for case in cases or load_start_cases()]


def render_results(results: list[CaseResult]) -> str:
    lines = [f"FAIL {r.case.name}: {'; '.join(r.failures)}" if r.failures else f"ok {r.case.name}" for r in results]
    passed = sum(not r.failures for r in results)
    return "\n".join([*lines, f"Score: {passed}/{len(results)}"])
