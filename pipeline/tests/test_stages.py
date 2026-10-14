import pytest

from pipeline.agent import FakeAgent
from pipeline.cost import BudgetExceeded, CostLedger
from pipeline.forge import FakeForge
from pipeline.run_dir import RunDir
from pipeline.stages import Pipeline, phase_count, phase_stage

PLAN = "# Plan\n## Phase 1: a\n## Phase 2: b\n"
DECISIONS = "## Decided\n- x\n## Escalated\n1. Pick a data model?\n"
STAGE_ORDER = [
    "issue", "analyze", "decide", "plan",
    "implement-phase-1", "implement-phase-2", "test", "docs",
]


def respond(prompt):
    if "/plan/SKILL.md" in prompt:
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
        self.ledger = CostLedger(self.run_dir.path / "cost.csv", budget)
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


def test_dry_run_walks_every_stage(tmp_path):
    h = Harness(tmp_path)
    assert h.pipeline().run() is None
    for name in ["issue", "analysis", "decisions", "plan", "phase-1-summary",
                 "phase-2-summary", "test-report", "pr"]:
        assert h.run_dir.exists(h.run_dir.artifact_path(name))
    assert len(h.agent.calls) == 8
    assert [row.split(",")[0] for row in h.ledger.path.read_text().splitlines()[1:]] == STAGE_ORDER
    assert h.ledger.total() == 4.0


def test_gate_a_shows_escalated_questions_and_stops_on_no(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q)
    assert h.pipeline().run() == "decide"
    assert "Pick a data model?" in h.shown[0]
    assert not h.run_dir.exists(h.run_dir.artifact_path("plan"))


def test_resume_skips_finished_stages_but_reasks_gates(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q)
    h.pipeline().run()
    calls_before = len(h.agent.calls)
    h.answers = None
    assert h.pipeline().run() is None
    assert len(h.agent.calls) - calls_before == 5
    assert sum("Escalated" in q for q in h.questions) == 2


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


def test_prompt_names_skill_inputs_and_output(tmp_path):
    h = Harness(tmp_path)
    prompt = h.pipeline().build_prompt(phase_stage(2))
    assert f"{tmp_path / 'skills' / 'implement-phase' / 'SKILL.md'}" in prompt
    assert str(h.run_dir.artifact_path("plan")) in prompt
    assert str(h.run_dir.artifact_path("phase-1-summary")) in prompt
    assert "Implement only phase 2" in prompt
    assert f"saved as {h.run_dir.artifact_path('phase-2-summary')}" in prompt


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


def test_resume_does_not_checkpoint_skipped_stages(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    h.pipeline().run()
    h.forge.calls.clear()
    h.options = {"stop_after": "decide"}
    h.pipeline().run()
    assert h.forge.calls == [("checkpoint", "decide")]


def test_blocked_stage_is_kept_aside_and_rerun_on_resume(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    assert h.pipeline().run() == "implement-phase-2"
    h.block_phase_2 = False
    assert not h.run_dir.exists(h.run_dir.artifact_path("phase-2-summary"))
    assert "tests fail twice" in (h.run_dir.path / "implement-phase-2.blocked.md").read_text()
    assert ("checkpoint", "implement-phase-2") in h.forge.calls
    assert h.pipeline().run() is None
