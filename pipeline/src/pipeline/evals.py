import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.agent import Agent
from pipeline.cost import CostLedger
from pipeline.forge import FakeForge
from pipeline.run_dir import RunDir
from pipeline.stages import DECIDE, PLAN, STATUS, Pipeline, closing_stages
from pipeline.validate import QUESTION, REFERENCE, decisions_problems, plan_problems

CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "cases"
REVIEW_CASES_DIR = CASES_DIR.parent / "review"
REVIEW_INPUTS = {"issue": "issue.md", "plan": "plan.md", "phase-1-summary": "summary.md", "test-report": "test-report.md"}
FINDINGS = re.compile(r"(?mis)^\W*Findings\W*$(.*?)(?=^\W*Axes\W*$|\Z)")
TOP_BULLET = re.compile(r"(?m)^[-*] ")
BLOCKING_LABEL = re.compile(r"\b(Critical|Required)\b")
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


@dataclass(frozen=True)
class ReviewCase:
    name: str
    path: Path
    expected: dict


def load_review_cases(directory: Path) -> list[ReviewCase]:
    return [
        ReviewCase(path.name, path, json.loads((path / "expected.json").read_text()))
        for path in sorted(directory.iterdir()) if path.is_dir()
    ]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.com", *args], cwd=repo, check=True, capture_output=True)


def build_repo(case: ReviewCase, dest: Path) -> Path:
    """Commits the case's base/ on main, then its head/ on top of it on a feature branch."""
    shutil.copytree(case.path / "base", dest)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "base")
    git(dest, "checkout", "-qb", "feature")
    shutil.copytree(case.path / "head", dest, dirs_exist_ok=True)
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "feature")
    return dest


def blocking_findings(review: str) -> list[str]:
    """Top-level bullets under Findings labelled Critical or Required, each with its sub-bullets."""
    findings = FINDINGS.search(review)
    blocks = TOP_BULLET.split(findings[1])[1:] if findings else []
    return [block for block in blocks if BLOCKING_LABEL.search(block.splitlines()[0])]


def cites(block: str, file: str, first: int, last: int) -> bool:
    return any(
        (path == file or path.endswith(f"/{file}")) and int(start) <= last and int(end or start) >= first
        for path, start, end in REFERENCE.findall(block)
    )


def review_failures(review: str, expected: dict) -> list[str]:
    status = STATUS.match(review)
    got = status[1].lower() if status else "missing"
    failures = [f"status: expected {expected['status']}, got {got}"] if got != expected["status"] else []
    blocking = blocking_findings(review)
    failures += [
        f"no Critical or Required finding cites {finding['file']}:{first}-{last}"
        for finding in expected["findings"]
        for first, last in [finding["lines"]]
        if not any(cites(block, finding["file"], first, last) for block in blocking)
    ]
    if not expected["findings"] and blocking:
        failures.append(f"{len(blocking)} Critical or Required finding(s) on a clean change")
    return failures


def run_review_case(case: ReviewCase, agent: Agent, skills_dir: Path, run_dir: RunDir) -> CaseResult:
    forge = FakeForge()
    forge.artifacts.update({name: (case.path / file).read_text() for name, file in REVIEW_INPUTS.items()})
    idea = forge.artifacts["issue"].splitlines()[0].removeprefix("# ")
    review = closing_stages(1)[1]
    pipeline = Pipeline(run_dir, CostLedger(), lambda _: agent, skills_dir, idea, lambda _: True, print, forge)
    result = agent.run(pipeline.build_prompt(review), review.model, CALL_BUDGET_USD)
    return CaseResult(case.name, review_failures(result.text, case.expected), result.cost_usd)


def run_review_evals(names: list[str], make_agent: Callable[[Path, Path], Agent], skills_dir: Path, workdir: Path) -> list[CaseResult]:
    cases = [case for case in load_review_cases(REVIEW_CASES_DIR) if not names or case.name in names]
    run_dir = RunDir(workdir, "eval")
    try:
        return [
            run_review_case(case, make_agent(build_repo(case, workdir / case.name), run_dir.staging), skills_dir, run_dir)
            for case in cases
        ]
    finally:
        run_dir.close()


def render_results(results: list[CaseResult]) -> str:
    lines = [f"{'PASS' if not r.failures else 'FAIL'} {r.name} (${r.cost_usd:.2f})" + "".join(f"\n  - {f}" for f in r.failures) for r in results]
    passed = sum(not r.failures for r in results)
    cost = sum(r.cost_usd for r in results)
    return "\n".join([*lines, f"Score: {passed}/{len(results)} cases clean, ${cost:.2f} spent"])
