import subprocess

from pipeline.agent import FakeAgent
from pipeline.run_dir import RunDir
from pipeline.evals import (
    CASES_DIR, REVIEW_CASES_DIR, build_repo, decide_buckets, load_cases, load_review_cases, review_failures, run_case,
    run_review_case,
)
from pipeline.cli import SKILLS_DIR

DECISIONS = """# Decisions

## Decided from evidence
- **Q1: a** — x. Evidence: `f:1`.

## Decided, low stakes
None.

## Escalated
- **Q2: b** — Why a human must decide: api.
"""
GOOD_PLAN = "## Phase 1: a\n- Verify: pytest\n\n## Phase 2: b\n- Verify: pytest -k b\n\n## Acceptance criteria\n- b works: Phase 2, `test_b`\n"


def test_decide_buckets_maps_questions_to_headings():
    assert decide_buckets(DECISIONS) == {"Q1": "evidence", "Q2": "escalated"}


def test_bundled_cases_load_and_include_an_escalation():
    cases = load_cases(CASES_DIR)
    assert len(cases) >= 3
    assert any(allowed == ["escalated"] for case in cases for allowed in case.expected.values())


def respond(decide, plan):
    return lambda prompt: decide if "/decide/SKILL.md" in prompt else plan


def test_run_case_scores_matching_buckets_and_good_plan(tmp_path):
    case = next(c for c in load_cases(CASES_DIR) if c.name == "public-api")
    decide = "## Decided from evidence\nNone.\n## Escalated\n- **Q1: x**\n## Decided, low stakes\n- **Q2: y**\n"
    result = run_case(case, FakeAgent(respond(decide, GOOD_PLAN), cost_usd=0.5), SKILLS_DIR, RunDir(tmp_path, 'eval'))
    assert result.failures == [] and result.cost_usd == 1.0


def test_run_case_reports_under_escalation_and_bad_plan(tmp_path):
    case = next(c for c in load_cases(CASES_DIR) if c.name == "public-api")
    decide = "## Decided, low stakes\n- **Q1: x**\n- **Q2: y**\n"
    result = run_case(case, FakeAgent(respond(decide, "nope")), SKILLS_DIR, RunDir(tmp_path, 'eval'))
    assert any("Q1" in failure and "low" in failure for failure in result.failures)
    assert any("Phase" in failure or "phase" in failure for failure in result.failures)


def test_run_case_reports_structural_decision_problems(tmp_path):
    case = next(c for c in load_cases(CASES_DIR) if c.name == "public-api")
    decide = "## Decided, low stakes\n- **Q2: y**\n## Escalated\n- **Q1: x**\n  Answer: _pending_\n"
    result = run_case(case, FakeAgent(respond(decide, GOOD_PLAN)), SKILLS_DIR, RunDir(tmp_path, "eval"))
    assert result.failures == ["decisions: missing a '## Decided from evidence' section"]
    result = run_case(case, FakeAgent(respond(decide.replace("Q2", "Q7"), GOOD_PLAN)), SKILLS_DIR, RunDir(tmp_path, "eval"))
    assert "decisions: no decision for Q2" in result.failures


REVIEW_FAIL = """Status: fail

**Findings**

- **Critical**, `app/users.py:9`: the email is put into the SQL string.
  - Fix: pass it as a parameter.
- Nit — `tests/test_users.py:4`: rename `make_db`.

**Axes**
- Security: `app/users.py:9`.
"""


def review_case(name):
    return next(c for c in load_review_cases(REVIEW_CASES_DIR) if c.name == name)


def test_bundled_review_cases_load_with_a_clean_case():
    cases = load_review_cases(REVIEW_CASES_DIR)
    assert len(cases) >= 4 and all((c.path / "base").is_dir() and (c.path / "head").is_dir() for c in cases)
    assert any(c.expected == {"status": "pass", "findings": []} for c in cases)


def test_build_repo_puts_the_change_on_a_feature_branch(tmp_path):
    repo = build_repo(review_case("sql-injection"), tmp_path / "repo")
    diff = subprocess.run(["git", "diff", "--name-only", "main...HEAD"], cwd=repo, capture_output=True, text=True, check=True)
    assert diff.stdout.split() == ["app/users.py", "tests/test_users.py"]


def test_review_failures_needs_a_blocking_finding_citing_the_planted_lines():
    expected = review_case("sql-injection").expected
    assert review_failures(REVIEW_FAIL, expected) == []
    assert review_failures(REVIEW_FAIL.replace("Critical", "Nit"), expected) == ["no Critical or Required finding cites app/users.py:9-10"]
    assert review_failures(REVIEW_FAIL.replace("users.py:9`:", "users.py:4`:"), expected) == ["no Critical or Required finding cites app/users.py:9-10"]
    assert review_failures("looks fine", expected)[0] == "status: expected fail, got missing"


def test_review_failures_flags_blocking_findings_on_a_clean_change():
    expected = {"status": "pass", "findings": []}
    assert review_failures("Status: pass\n\n**Findings**\nNone.\n", expected) == []
    assert review_failures(REVIEW_FAIL.replace("fail", "pass", 1), expected) == ["1 Critical or Required finding(s) on a clean change"]


def test_run_review_case_runs_the_review_skill_on_the_staged_inputs(tmp_path):
    agent = FakeAgent(lambda prompt: REVIEW_FAIL, cost_usd=0.6)
    result = run_review_case(review_case("sql-injection"), agent, SKILLS_DIR, RunDir(tmp_path, "eval"))
    assert result.failures == [] and result.cost_usd == 0.6
    prompt, model, _ = agent.calls[0]
    assert "/review/SKILL.md" in prompt and "test-report.md" in prompt and model == "opus"
