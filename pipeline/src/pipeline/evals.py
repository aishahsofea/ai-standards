import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.agent import Agent
from pipeline.cost import CostLedger
from pipeline.forge import FakeForge
from pipeline.run_dir import RunDir
from pipeline.stages import DECIDE, PLAN, Pipeline
from pipeline.validate import QUESTION, decisions_problems, plan_problems

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "cases"
CALL_BUDGET_USD = 2.0
BUCKET_HEADINGS = {"Decided from evidence": "evidence", "Decided, low stakes": "low", "Escalated": "escalated"}


@dataclass(frozen=True)
class Case:
    name: str
    issue: str
    analysis: str
    decisions: str
    expected: dict[str, list[str]]


@dataclass(frozen=True)
class CaseResult:
    name: str
    failures: list[str]
    cost_usd: float


def load_cases(directory: Path) -> list[Case]:
    return [
        Case(
            path.name, (path / "issue.md").read_text(), (path / "analysis.md").read_text(),
            (path / "decisions.md").read_text(), json.loads((path / "expected.json").read_text()),
        )
        for path in sorted(directory.iterdir()) if path.is_dir()
    ]


def decide_buckets(decisions: str) -> dict[str, str]:
    buckets: dict[str, str] = {}
    bucket = ""
    for line in decisions.splitlines():
        if line.startswith("## "):
            bucket = BUCKET_HEADINGS.get(line[3:].strip(), "")
        elif bucket and (match := QUESTION.search(line)):
            buckets[match[1]] = bucket
    return buckets


def run_case(case: Case, agent: Agent, skills_dir: Path, run_dir: RunDir) -> CaseResult:
    forge = FakeForge()
    forge.artifacts.update(issue=case.issue, analysis=case.analysis, decisions=case.decisions)
    pipeline = Pipeline(run_dir, CostLedger(), lambda _: agent, skills_dir, case.name, lambda _: True, print, forge)
    decided = agent.run(pipeline.build_prompt(DECIDE), DECIDE.model, CALL_BUDGET_USD)
    planned = agent.run(pipeline.build_prompt(PLAN), PLAN.model, CALL_BUDGET_USD)
    got = decide_buckets(decided.text)
    failures = [
        f"{question}: expected {'/'.join(allowed)}, got {got.get(question, 'missing')}"
        for question, allowed in case.expected.items() if got.get(question) not in allowed
    ]
    failures += [f"decisions: {problem}" for problem in decisions_problems(decided.text, case.analysis)]
    failures += plan_problems(planned.text)
    return CaseResult(case.name, failures, decided.cost_usd + planned.cost_usd)


def run_evals(names: list[str], make_agent: Callable[[Path], Agent], skills_dir: Path, workdir: Path) -> list[CaseResult]:
    cases = [case for case in load_cases(CASES_DIR) if not names or case.name in names]
    run_dir = RunDir(workdir, "eval")
    try:
        agent = make_agent(run_dir.staging)
        return [run_case(case, agent, skills_dir, run_dir) for case in cases]
    finally:
        run_dir.close()


def render_results(results: list[CaseResult]) -> str:
    lines = [f"{'PASS' if not r.failures else 'FAIL'} {r.name} (${r.cost_usd:.2f})" + "".join(f"\n  - {f}" for f in r.failures) for r in results]
    passed = sum(not r.failures for r in results)
    cost = sum(r.cost_usd for r in results)
    return "\n".join([*lines, f"Score: {passed}/{len(results)} cases clean, ${cost:.2f} spent"])
