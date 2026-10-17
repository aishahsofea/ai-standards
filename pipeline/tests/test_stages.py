from pathlib import Path

import pytest

from pipeline.agent import FakeAgent
from pipeline.cost import BudgetExceeded, CostLedger
from pipeline.forge import FakeForge, ForgeError
from pipeline.run_dir import RunDir
from pipeline.stages import ISSUE, Pipeline, phase_count, phase_stage

PLAN = "# Plan\n## Phase 1: a\n## Phase 2: b\n"
DECISIONS = "## Decided\n- x\n## Escalated\n1. Pick a data model?\n"
PLAN_INPUTS: list[str] = []
STAGE_ORDER = [
    "issue", "analyze", "decide", "plan",
    "implement-phase-1", "implement-phase-2", "test", "docs",
]


def staged(prompt, name):
    line = next(line for line in prompt.splitlines() if line.endswith(f"/{name}.md"))
    return Path(line.removeprefix("- ")).read_text()


def respond(prompt):
    if "/plan/SKILL.md" in prompt:
        PLAN_INPUTS.append(staged(prompt, "decisions"))
        return PLAN
    if "/decide/SKILL.md" in prompt:
        return DECISIONS
    if "/forge-cli/SKILL.md" in prompt:
        return "# Add dark mode\n\nbody"
    return "content"


class Harness:
    def __init__(self, tmp_path, answers=None, budget=15.0, cost=0.5, **options):
        self.tmp_path = tmp_path
        self.run_dir = RunDir(tmp_path, "feat")
        self.ledger = CostLedger(budget)
        self.block_phase_2 = False
        self.agent = FakeAgent(self._respond, cost_usd=cost)
        self.forge = FakeForge()
        self.questions: list[str] = []
        self.shown: list[str] = []
        self.answers = answers
        self.options = options

    def _respond(self, prompt):
        if self.block_phase_2 and "Implement only phase 2" in prompt:
            return "Status: blocked - tests fail twice"
        return respond(prompt)

    def confirm(self, question):
        self.questions.append(question)
        return self.answers(question) if self.answers else True

    def pipeline(self):
        return Pipeline(
            self.run_dir, self.ledger, lambda stage: self.agent, self.tmp_path / "skills",
            "an idea", self.confirm, self.shown.append, self.forge, **self.options,
        )

    def called_stages(self):
        return [name for name in STAGE_ORDER if any(
            f"/{self.skill(name)}/SKILL.md" in call[0] for call in self.agent.calls)]

    @staticmethod
    def skill(stage_name):
        return {"issue": "forge-cli", "analyze": "analyze-issue"}.get(
            stage_name, "implement-phase" if stage_name.startswith("implement") else stage_name)


@pytest.fixture(autouse=True)
def clear_plan_inputs():
    PLAN_INPUTS.clear()


def test_dry_run_walks_every_stage(tmp_path):
    h = Harness(tmp_path)
    assert h.pipeline().run() is None
    assert set(h.forge.artifacts) == {
        "issue", "analysis", "decisions", "plan", "phase-1-summary",
        "phase-2-summary", "test-report", "pr",
    }
    assert len(h.agent.calls) == 8
    assert [record[0] for record in h.ledger.records] == STAGE_ORDER
    assert h.ledger.total() == 4.0


def test_nothing_is_written_under_agent_runs(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    assert list((tmp_path / ".agent").rglob("*.md")) == []


def test_gate_a_shows_escalated_questions_and_stops_on_no(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q)
    assert h.pipeline().run() == "decide"
    assert "Pick a data model?" in h.shown[0]
    assert not h.forge.has_artifact("plan")


def test_resume_skips_stages_with_a_comment_and_never_reposts(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q)
    h.pipeline().run()
    calls_before = len(h.agent.calls)
    h.answers = None
    assert h.pipeline().run() is None
    assert len(h.agent.calls) - calls_before == 5
    assert sum("Escalated" in q for q in h.questions) == 2
    assert sorted(h.forge.posts) == sorted(set(h.forge.posts))


def test_existing_issue_skips_the_issue_stage(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    h.forge.artifacts["issue"] = "# Existing\n\nbody"
    h.pipeline().run()
    assert h.called_stages() == ["analyze"]
    assert ("open_issue", "Add dark mode") not in h.forge.calls


def test_pause_after_each_executed_stage(tmp_path):
    h = Harness(tmp_path, answers=lambda q: not q.startswith("analyze"))
    assert h.pipeline().run() == "analyze"
    assert h.called_stages() == ["issue", "analyze"]


def test_pause_each_off_only_asks_at_gates(tmp_path):
    h = Harness(tmp_path, pause_each=False)
    h.pipeline().run()
    assert len(h.questions) == 2


def test_stop_after(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    assert h.pipeline().run() == "analyze"
    assert len(h.agent.calls) == 2


def test_budget_stops_between_stages(tmp_path):
    h = Harness(tmp_path, budget=1.0, cost=0.6)
    with pytest.raises(BudgetExceeded):
        h.pipeline().run()
    assert len(h.agent.calls) == 2


def test_agent_gets_remaining_budget_and_stage_model(tmp_path):
    h = Harness(tmp_path, budget=10.0, cost=1.0, stop_after="analyze")
    h.pipeline().run()
    assert [(c[1], c[2]) for c in h.agent.calls] == [("sonnet", 10.0), ("opus", 9.0)]


def test_prompt_lists_staged_inputs_outside_the_repo(tmp_path):
    h = Harness(tmp_path)
    h.forge.artifacts.update({"plan": PLAN, "phase-1-summary": "did phase 1"})
    prompt = h.pipeline().build_prompt(phase_stage(2))
    assert f"{tmp_path / 'skills' / 'implement-phase' / 'SKILL.md'}" in prompt
    assert staged(prompt, "plan") == PLAN
    assert staged(prompt, "phase-1-summary") == "did phase 1"
    assert ".agent/runs" not in prompt
    assert str(tmp_path) not in prompt.split("Input files:")[1]
    assert "Implement only phase 2" in prompt
    assert "Your final reply is posted as the phase-2-summary comment; make it the complete document." in prompt


def test_issue_prompt_says_reply_becomes_the_issue_body(tmp_path):
    prompt = Harness(tmp_path).pipeline().build_prompt(ISSUE)
    assert "Input files" not in prompt
    assert "posted as the issue body" in prompt


def test_missing_input_artifact_is_an_error(tmp_path):
    with pytest.raises(ForgeError, match="plan"):
        Harness(tmp_path).pipeline().build_prompt(phase_stage(1))


def test_phase_count():
    assert phase_count(PLAN) == 2


@pytest.mark.parametrize("plan", ["no phases", "## Phase 2: a", "## Phase 1\n## Phase 3"])
def test_phase_count_rejects_bad_plans(plan):
    with pytest.raises(ValueError):
        phase_count(plan)


def test_forge_gets_issue_then_checkpoint_per_executed_stage(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    assert h.forge.calls[:2] == [("open_issue", "Add dark mode"), ("checkpoint", "issue")]
    assert [c[1] for c in h.forge.calls if c[0] == "checkpoint"] == STAGE_ORDER
    assert h.forge.calls[-1] == ("finish", "content")


def test_declining_gate_b_does_not_finish(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Mark the PR" not in q)
    assert h.pipeline().run() == "docs"
    assert all(call[0] != "finish" for call in h.forge.calls)


def test_gate_b_finishes_with_the_latest_pr_comment(tmp_path):
    def edit_pr(question):
        if "Mark the PR" in question:
            h.forge.artifacts["pr"] = "edited on GitHub"
        return True

    h = Harness(tmp_path, answers=edit_pr)
    h.pipeline().run()
    assert h.forge.calls[-1] == ("finish", "edited on GitHub")


def test_gate_a_picks_up_an_edited_decisions_comment_and_later_replies(tmp_path):
    def answer(question):
        if "Escalated" in question:
            h.forge.artifacts["decisions"] = "## Escalated\n1. Pick a data model?\nAnswer: sqlite"
            h.forge.replies = ["also keep it offline"]
        return True

    h = Harness(tmp_path, answers=answer)
    h.pipeline().run()
    (seen,) = PLAN_INPUTS
    assert "Answer: sqlite" in seen
    assert "also keep it offline" in seen


def test_plan_input_without_replies_is_the_decisions_comment(tmp_path):
    Harness(tmp_path).pipeline().run()
    assert PLAN_INPUTS == [DECISIONS]


def test_resume_does_not_checkpoint_skipped_stages(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    h.pipeline().run()
    h.forge.calls.clear()
    h.options = {"stop_after": "decide"}
    h.pipeline().run()
    assert h.forge.calls == [("checkpoint", "decide")]


def test_blocked_stage_posts_report_without_checkpoint_and_reruns_on_resume(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    assert h.pipeline().run() == "implement-phase-2"
    assert "tests fail twice" in h.forge.artifacts["implement-phase-2.blocked"]
    assert "implement-phase-2.blocked" in h.shown[-1]
    assert not h.forge.has_artifact("phase-2-summary")
    assert ("checkpoint", "implement-phase-2") not in h.forge.calls
    assert ("checkpoint", "implement-phase-1") in h.forge.calls
    h.block_phase_2 = False
    assert h.pipeline().run() is None
    assert ("checkpoint", "implement-phase-2") in h.forge.calls


def test_rerunning_a_blocked_stage_edits_the_same_comment(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    h.pipeline().run()
    h.pipeline().run()
    assert h.forge.posts.count("implement-phase-2.blocked") == 2
    assert len([name for name in h.forge.artifacts if name.endswith(".blocked")]) == 1
