from pipeline.agent import FakeAgent
from pipeline.run_dir import RunDir
from pipeline.evals import CASES_DIR, decide_buckets, load_cases, run_case
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
