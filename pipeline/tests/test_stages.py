from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.agent import Denial, FakeAgent, Result
from pipeline.checks import CheckRun
from pipeline.cost import BudgetExceeded, CostLedger
from pipeline.forge import Check, FakeForge, ForgeError
from pipeline.run_dir import RunDir
from pipeline.stages import ISSUE, Pipeline, phase_count, phase_stage

CRITERIA = "## Acceptance criteria\n- it works: Phase 1, `test_a`\n"
PLAN = f"# Plan\n## Phase 1: a\n- Verify: pytest\n## Phase 2: b\n- Verify: pytest\n{CRITERIA}"
ANALYSIS = "# Analysis\n\n## Open questions\n- **Q1:** Pick a data model?\n"
DECISIONS = "## Decided from evidence\nNone.\n## Decided, low stakes\nNone.\n## Escalated\n1. **Q1:** Pick a data model?\n"
PLAN_INPUTS: list[str] = []
STAGE_ORDER = [
    "issue", "analyze", "decide", "plan",
    "implement-phase-1", "implement-phase-2", "test", "review", "docs",
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
    if "/analyze/SKILL.md" in prompt:
        return ANALYSIS
    if "/forge-cli/SKILL.md" in prompt:
        return "# Add dark mode\n\nbody"
    if "/implement-phase/SKILL.md" in prompt:
        return "Status: done\nok"
    if "/test/SKILL.md" in prompt:
        return "Status: pass\nok"
    if "/review/SKILL.md" in prompt:
        return "Status: pass\nok"
    if "/revise/SKILL.md" in prompt:
        return "Status: done\nrevised"
    if "/fix/SKILL.md" in prompt:
        return "Status: done\nfixed"
    if "/ci-fix/SKILL.md" in prompt:
        return "Status: done\n- **Check** lint: fixed the import order"
    return "content"


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


RUN_LINK = "https://github.com/o/r/actions/runs/5/job/1"


class Harness:
    def __init__(self, tmp_path, answers=None, budget=15.0, cost=0.5, **options):
        self.tmp_path = tmp_path
        self.run_dir = RunDir(tmp_path, "feat")
        self.ledger = CostLedger(budget)
        self.block_phase_2 = False
        self.phase_1_reply = None
        self.plan = None
        self.review_reply = None
        self.queued: dict[str, list[str]] = {}
        self.follow_ups: list[str] = []
        self.last = ""
        self.agent = FakeAgent(self._respond, cost_usd=cost)
        self.forge = FakeForge()
        self.questions: list[str] = []
        self.shown: list[str] = []
        self.answers = answers
        self.clock = Clock()
        self.options = {"ask": lambda _: "sqlite", "sleep": self.clock.sleep, "clock": self.clock, **options}

    def _respond(self, prompt):
        if prompt.startswith("Reply with your report only"):
            return self.follow_ups.pop(0) if self.follow_ups else self.last
        self.last = self._reply(prompt)
        return self.last

    def _reply(self, prompt):
        for skill, replies in self.queued.items():
            if replies and f"/{skill}/SKILL.md" in prompt:
                return replies.pop(0)
        if self.block_phase_2 and "Implement only phase 2" in prompt:
            return "Status: blocked - tests fail twice"
        if self.phase_1_reply and "Implement only phase 1" in prompt:
            return self.phase_1_reply
        if self.review_reply and "/review/SKILL.md" in prompt:
            return self.review_reply
        if self.plan and "/plan/SKILL.md" in prompt:
            return self.plan
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
        return {"issue": "forge-cli", "analyze": "analyze"}.get(
            stage_name, "implement-phase" if stage_name.startswith("implement") else stage_name)


@pytest.fixture(autouse=True)
def clear_plan_inputs():
    PLAN_INPUTS.clear()


def test_dry_run_walks_every_stage(tmp_path):
    h = Harness(tmp_path)
    assert h.pipeline().run() is None
    assert set(h.forge.artifacts) == {
        "issue", "analysis", "decisions", "plan", "phase-1-summary",
        "phase-2-summary", "test-report", "review", "pr",
    }
    assert len(h.agent.calls) == 9
    assert [record[0] for record in h.ledger.records] == STAGE_ORDER
    assert h.ledger.total() == 4.5


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
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q, ask=None)
    h.pipeline().run()
    calls_before = len(h.agent.calls)
    h.forge.artifacts["decisions"] += "  Answer: sqlite\n"
    h.answers = None
    assert h.pipeline().run() is None
    assert len(h.agent.calls) - calls_before == 6
    assert sum("Escalated" in q for q in h.questions) == 1
    assert sorted(h.forge.posts) == sorted(set(h.forge.posts))


def test_existing_issue_skips_the_issue_stage(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    h.forge.artifacts["issue"] = "# Existing\n\nbody"
    h.pipeline().run()
    assert h.called_stages() == ["analyze"]
    assert ("open_issue", "Add dark mode") not in h.forge.calls


def test_pause_each_asks_after_every_executed_stage(tmp_path):
    h = Harness(tmp_path, pause_each=True, answers=lambda q: not q.startswith("analyze"))
    assert h.pipeline().run() == "analyze"
    assert h.called_stages() == ["issue", "analyze"]


def test_by_default_only_the_gates_and_the_plan_ask(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    assert [q.split()[0] for q in h.questions] == ["Escalated", "plan", "Reviewed"]


def test_notifies_at_each_prompt(tmp_path):
    notes = []
    h = Harness(tmp_path, notify=notes.append)
    h.pipeline().run()
    assert [note.split()[0] for note in notes] == ["decide", "plan", "docs"]


def prompts_for(h, skill):
    return [call[0] for call in h.agent.calls if f"/{skill}/SKILL.md" in call[0]]


def test_preflight_posts_a_passing_baseline_without_asking(tmp_path):
    h = Harness(tmp_path, checks=lambda: [CheckRun("pytest", True)])
    h.pipeline().run()
    assert "Every check passed" in h.forge.artifacts["baseline"]
    assert not [q for q in h.questions if q.startswith("These checks fail")]
    assert h.forge.posts.index("baseline") < h.forge.posts.index("analysis")


def test_declining_a_failing_baseline_stops_before_analyze(tmp_path):
    h = Harness(tmp_path, checks=lambda: [CheckRun("pytest", False, "9 failed")], answers=lambda q: not q.startswith("These checks fail"))
    assert h.pipeline().run() == "preflight"
    assert h.called_stages() == ["issue"]
    assert "9 failed" in h.shown[-1] and "baseline" not in h.forge.artifacts


def test_accepted_baseline_failures_reach_the_stages_that_run_checks(tmp_path):
    h = Harness(tmp_path, checks=lambda: [CheckRun("pytest", False, "9 failed")])
    h.pipeline().run()
    for skill in ("implement-phase", "test"):
        assert "9 failed" in staged(prompts_for(h, skill)[0], "baseline")
    for skill in ("plan", "review", "docs"):
        assert "/baseline.md" not in prompts_for(h, skill)[0]


def test_preflight_does_not_run_once_analysis_exists(tmp_path):
    ran = []
    h = Harness(tmp_path, checks=lambda: ran.append(1) or [CheckRun("pytest", True)])
    h.forge.artifacts.update(issue="# T", analysis=ANALYSIS)
    h.pipeline().run()
    assert not ran and "baseline" not in h.forge.artifacts


def test_plan_prompt_shows_preview_and_declining_stops(tmp_path):
    h = Harness(tmp_path, answers=lambda q: not q.startswith("plan done"))
    h.plan = f"## Assumptions\n- a1\n## Phase 1: schema\n- Verify: pytest\n{CRITERIA}## Out of scope\n- o1\n"
    assert h.pipeline().run() == "plan"
    preview = h.shown[-1]
    assert "1. schema" in preview and "a1" in preview and "o1" in preview
    assert h.questions[-1].startswith("plan done")
    assert "implement-phase-1" not in h.called_stages()


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
    assert h.forge.calls[:2] == [("open_issue", "Add dark mode"), ("checkpoint", "pipeline: issue")]
    assert [c[1] for c in h.forge.calls if c[0] == "checkpoint"] == [
        {"implement-phase-1": "phase 1: a", "implement-phase-2": "phase 2: b"}.get(name, f"pipeline: {name}")
        for name in STAGE_ORDER
    ]
    assert h.forge.calls[-1] == ("finish", "content")


def test_declining_gate_b_does_not_finish(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Mark the PR" not in q, ask=lambda p: "" if "What should change" in p else "sqlite")
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


def test_gate_a_terminal_answers_are_posted_to_the_decisions_comment(tmp_path):
    h = Harness(tmp_path, ask=lambda _: "sqlite")
    h.pipeline().run()
    assert "Answer: sqlite" in h.forge.artifacts["decisions"]
    assert (seen := PLAN_INPUTS[-1]) and "Answer: sqlite" in seen


def test_plan_input_without_replies_is_the_decisions_comment(tmp_path):
    Harness(tmp_path).pipeline().run()
    assert PLAN_INPUTS == [DECISIONS + "  Answer: sqlite\n"]


def test_each_phase_gets_its_own_titled_checkpoint(tmp_path):
    h = Harness(tmp_path)
    h.plan = f"# Plan\n## Phase 1: schema\n- Verify: x\n## Phase 2: api\n- Verify: x\n### Phase 3: ui\n- Verify: x\n{CRITERIA}"
    h.pipeline().run()
    commits = [c[1] for c in h.forge.calls if c[0] == "checkpoint" and c[1].startswith("phase")]
    assert commits == ["phase 1: schema", "phase 2: api", "phase 3: ui"]


def skill_calls(h, skill):
    return [call[0] for call in h.agent.calls if f"/{skill}/SKILL.md" in call[0]]


def test_failed_review_runs_one_fix_round_then_continues(tmp_path):
    h = Harness(tmp_path)
    h.queued["review"] = ["Status: fail\n- Critical: SQL injection"]
    assert h.pipeline().run() is None
    assert "SQL injection" in staged(skill_calls(h, "fix")[0], "review.blocked")
    assert len(skill_calls(h, "test")) == 2
    assert "fixed" in staged(skill_calls(h, "review")[1], "fix-summary")
    assert h.forge.has_artifact("review") and h.forge.has_artifact("pr")
    assert ("checkpoint", "pipeline: fix review findings") in h.forge.calls


def test_review_failing_after_fix_round_blocks_and_docs_never_runs(tmp_path):
    h = Harness(tmp_path)
    h.review_reply = "Status: fail\n- Critical: SQL injection"
    assert h.pipeline().run() == "review"
    assert len(skill_calls(h, "fix")) == 1
    assert "SQL injection" in h.forge.artifacts["review.blocked"]
    assert not h.forge.has_artifact("review")
    assert "docs" not in h.called_stages()


def test_resume_after_a_failed_review_starts_with_the_fix_round(tmp_path):
    h = Harness(tmp_path)
    h.review_reply = "Status: fail\n- Critical: SQL injection"
    h.pipeline().run()
    h.review_reply = None
    h.agent.calls.clear()
    assert h.pipeline().run() is None
    assert [Harness.skill(name) for name in h.called_stages()] == ["test", "review", "docs"]
    assert "SQL injection" in staged(skill_calls(h, "fix")[0], "review.blocked")
    review = skill_calls(h, "review")[0]
    assert "SQL injection" in staged(review, "review.blocked") and "fixed" in staged(review, "fix-summary")
    assert "Recheck every finding in review.blocked" in review


def test_owner_replies_after_a_failed_review_reach_fix_and_rereview(tmp_path):
    h = Harness(tmp_path)
    h.forge.replies = ["Owner sign-off: keep this fixture"]
    h.queued["review"] = ["Status: fail\n- Required: fixture lacks evidence"]
    assert h.pipeline().run() is None
    for prompt in (skill_calls(h, "fix")[0], skill_calls(h, "review")[1]):
        blocked = staged(prompt, "review.blocked")
        assert "## Replies on the issue" in blocked and "keep this fixture" in blocked


def test_resume_after_a_malformed_review_reruns_the_review(tmp_path):
    h = Harness(tmp_path)
    h.review_reply = "looks fine"
    assert h.pipeline().run() == "review"
    h.review_reply = None
    h.agent.calls.clear()
    assert h.pipeline().run() is None
    assert skill_calls(h, "fix") == []
    assert len(skill_calls(h, "review")) == 1


def test_plan_without_acceptance_criteria_is_retried_then_blocks(tmp_path):
    h = Harness(tmp_path)
    h.plan = "# Plan\n## Phase 1: a\n- Verify: pytest\n"
    assert h.pipeline().run() == "plan"
    assert "missing a '## Acceptance criteria' section" in h.forge.artifacts["plan.blocked"]
    assert sum("/plan/SKILL.md" in call[0] for call in h.agent.calls) == 2


def test_blocked_fix_stops_before_retesting(tmp_path):
    h = Harness(tmp_path)
    h.queued["review"] = ["Status: fail\n- Critical: SQL injection"]
    h.queued["fix"] = ["Status: blocked - test fails twice"]
    assert h.pipeline().run() == "fix"
    assert "test fails twice" in h.forge.artifacts["fix.blocked"]
    assert len(skill_calls(h, "test")) == 1


def test_review_is_read_only_and_docs_reads_it(tmp_path):
    from pipeline.stages import closing_stages

    test, review, docs = closing_stages(2)
    assert review.read_only and not test.read_only
    assert (review.model, review.max_turns, review.statuses) == ("opus", 30, ("pass", "fail"))
    assert review.inputs == ("issue", "plan", "phase-1-summary", "phase-2-summary", "test-report")
    assert "review" in docs.inputs


def test_resume_does_not_checkpoint_skipped_stages(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    h.pipeline().run()
    h.forge.calls.clear()
    h.options = {"stop_after": "decide"}
    h.pipeline().run()
    assert h.forge.calls == [("checkpoint", "pipeline: decide")]


def test_blocked_stage_posts_report_without_checkpoint_and_reruns_on_resume(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    assert h.pipeline().run() == "implement-phase-2"
    assert "tests fail twice" in h.forge.artifacts["implement-phase-2.blocked"]
    assert "implement-phase-2.blocked" in h.shown[-1]
    assert not h.forge.has_artifact("phase-2-summary")
    assert ("checkpoint", "phase 2: b") not in h.forge.calls
    assert ("checkpoint", "phase 1: a") in h.forge.calls
    h.block_phase_2 = False
    assert h.pipeline().run() is None
    assert ("checkpoint", "phase 2: b") in h.forge.calls


class DenyingAgent(FakeAgent):
    def __init__(self, respond):
        super().__init__(respond)
        self.denied_once = False

    def run(self, prompt, model, budget, resume=None):
        result = super().run(prompt, model, budget, resume)
        if "Implement only phase 2" in prompt and not self.denied_once:
            self.denied_once = True
            return Result(result.text, 0.0, (Denial("Bash", "docker ps"),))
        return result


def test_approved_denial_reruns_the_blocked_stage_without_posting_blocked(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    h.agent = DenyingAgent(h._respond)
    seen = []

    def approve(denials):
        seen.append(denials)
        h.block_phase_2 = False
        return True

    h.options["approve"] = approve
    assert h.pipeline().run() is None
    assert seen == [(Denial("Bash", "docker ps"),)]
    assert not h.forge.has_artifact("implement-phase-2.blocked")
    assert h.forge.has_artifact("phase-2-summary")


def test_declined_denial_still_blocks(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    h.agent = DenyingAgent(h._respond)
    h.options["approve"] = lambda denials: False
    assert h.pipeline().run() == "implement-phase-2"
    assert h.forge.has_artifact("implement-phase-2.blocked")


@pytest.mark.parametrize("reply", ["no status here", "Status: maybe", "Status: pass"])
def test_missing_or_invalid_status_blocks_phase(tmp_path, reply):
    h = Harness(tmp_path)
    h.phase_1_reply = reply
    assert h.pipeline().run() == "implement-phase-1"
    assert reply in h.forge.artifacts["implement-phase-1.blocked"]
    assert "Status: done|blocked" in h.forge.artifacts["implement-phase-1.blocked"]
    assert not h.forge.has_artifact("phase-1-summary")


MONITOR_REPLY = "Monitor event matches the results already in the summary above."


def full_phase_1_calls(h):
    return sum("Implement only phase 1" in call[0] for call in h.agent.calls)


def test_phase_with_no_status_line_resumes_the_session_for_a_report(tmp_path):
    h = Harness(tmp_path)
    h.phase_1_reply = MONITOR_REPLY
    h.follow_ups = ["Status: done\nthe summary"]
    assert h.pipeline().run() is None
    assert h.forge.artifacts["phase-1-summary"] == "Status: done\nthe summary"
    assert full_phase_1_calls(h) == 1
    assert [prompt for prompt, _ in h.agent.resumes] == ["Reply with your report only. The first line must be `Status: done|blocked`."]
    assert [record[0] for record in h.ledger.records].count("implement-phase-1") == 2


def test_phase_still_blocks_when_the_resumed_reply_has_no_status(tmp_path):
    h = Harness(tmp_path)
    h.phase_1_reply = MONITOR_REPLY
    h.follow_ups = ["still nothing"]
    assert h.pipeline().run() == "implement-phase-1"
    assert h.forge.artifacts["implement-phase-1.blocked"] == (
        "Status: blocked - reply must start with `Status: done|blocked`\n\nstill nothing"
    )
    assert len(h.agent.resumes) == 1


def test_status_retry_is_billed_against_the_remaining_budget(tmp_path):
    h = Harness(tmp_path)
    h.phase_1_reply = MONITOR_REPLY
    h.pipeline().run()
    assert h.agent.calls[-1][2] == 15.0 - 2.5


def test_status_retry_stops_when_the_first_reply_used_up_the_budget(tmp_path):
    h = Harness(tmp_path, budget=2.2)
    h.phase_1_reply = MONITOR_REPLY
    with pytest.raises(BudgetExceeded):
        h.pipeline().run()
    assert h.agent.resumes == []


def test_status_retry_without_a_session_id_reruns_with_the_previous_reply(tmp_path):
    class NoSession(FakeAgent):
        def run(self, prompt, model, budget, resume=None):
            return replace(super().run(prompt, model, budget, resume), session_id="")

    h = Harness(tmp_path)
    h.agent = NoSession(h._respond, cost_usd=0.5)
    h.phase_1_reply = MONITOR_REPLY
    assert h.pipeline().run() == "implement-phase-1"
    retry = h.agent.calls[-1][0]
    assert "Implement only phase 1" in retry and f"Previous reply:\n{MONITOR_REPLY}" in retry
    assert h.agent.resumes == []


def test_an_explicit_blocked_status_is_not_retried(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    h.pipeline().run()
    assert h.agent.resumes == []


def test_stages_without_a_status_list_are_not_retried(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    assert h.agent.resumes == []


def test_rerunning_a_blocked_stage_edits_the_same_comment(tmp_path):
    h = Harness(tmp_path)
    h.block_phase_2 = True
    h.pipeline().run()
    h.pipeline().run()
    assert h.forge.posts.count("implement-phase-2.blocked") == 2
    assert len([name for name in h.forge.artifacts if name.endswith(".blocked")]) == 1


def test_resume_skips_gate_a_once_questions_are_answered(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q)
    h.pipeline().run()
    h.forge.artifacts["decisions"] = "## Escalated\n- **Q1: a**\n  Answer: sqlite\n"
    h.questions.clear()
    h.answers = None
    h.pipeline().run()
    assert not any("Escalated" in q for q in h.questions)


def test_resume_still_asks_gate_a_while_questions_are_pending(tmp_path):
    h = Harness(tmp_path, answers=lambda q: "Escalated" not in q, ask=None)
    h.pipeline().run()
    h.questions.clear()
    h.answers = None
    h.pipeline().run()
    assert sum("Escalated" in q for q in h.questions) == 1


def test_gate_a_refuses_to_continue_while_questions_are_unanswered(tmp_path):
    h = Harness(tmp_path, ask=lambda _: "")
    assert h.pipeline().run() == "decide"
    assert "still have no answer" in h.shown[-1]
    assert not h.forge.has_artifact("plan")


def test_gate_a_continues_when_answers_are_added_on_github_before_approving(tmp_path):
    def approve(question):
        h.forge.artifacts["decisions"] = "## Escalated\n1. Pick a data model?\nAnswer: sqlite"
        return True

    h = Harness(tmp_path, ask=lambda _: "", answers=approve)
    assert h.pipeline().run() is None


def test_invalid_analysis_is_retried_once_with_the_problems(tmp_path):
    h = Harness(tmp_path, stop_after="analyze")
    h.queued["analyze"] = ["# Analysis\nno questions section"]
    assert h.pipeline().run() == "analyze"
    retry = h.agent.calls[-1][0]
    assert "missing a '## Open questions' section" in retry and "no questions section" in retry
    assert h.forge.artifacts["analysis"] == ANALYSIS
    assert len(h.agent.calls) == 3 and h.ledger.total() == 1.5


def test_decisions_missing_a_question_block_after_one_retry(tmp_path):
    h = Harness(tmp_path)
    h.queued["decide"] = ["## Decided from evidence\nNone.\n## Decided, low stakes\nNone.\n## Escalated\nNone.\n"] * 2
    assert h.pipeline().run() == "decide"
    assert "no decision for Q1" in h.forge.artifacts["decide.blocked"]
    assert not h.forge.has_artifact("decisions")
    assert ("checkpoint", "pipeline: decide") not in h.forge.calls
    assert [call[1] for call in h.agent.calls].count("opus") == 3


def test_decisions_citing_a_missing_file_block(tmp_path):
    h = Harness(tmp_path)
    cited = DECISIONS.replace("None.\n## Decided, low", "- **Q2: x** - y. Evidence: `src/gone.py:4`.\n## Decided, low")
    h.queued["decide"] = [cited, cited]
    assert h.pipeline().run() == "decide"
    assert "`src/gone.py` does not exist" in h.forge.artifacts["decide.blocked"]


def test_a_blocked_analysis_reply_is_not_retried(tmp_path):
    h = Harness(tmp_path)
    h.queued["analyze"] = ["Status: blocked - issue is unreadable"]
    assert h.pipeline().run() == "analyze"
    assert len(h.agent.calls) == 2


def test_gate_a_revisit_answer_reruns_decide_with_the_decisions_as_input(tmp_path):
    h = Harness(tmp_path, ask=lambda _: "!sqlite")
    h.queued["decide"] = [DECISIONS, DECISIONS + "  Answer: sqlite\n"]
    h.pipeline().run()
    decides = [call for call in h.agent.calls if "/decide/SKILL.md" in call[0]]
    assert len(decides) == 2
    assert "decisions.md" in decides[1][0] and "remove each '[revisit]'" in decides[1][0]
    assert PLAN_INPUTS[-1] == DECISIONS + "  Answer: sqlite\n"


def test_gate_a_plain_answers_do_not_rerun_decide(tmp_path):
    h = Harness(tmp_path, ask=lambda _: "sqlite")
    h.pipeline().run()
    assert sum("/decide/SKILL.md" in call[0] for call in h.agent.calls) == 1


def test_revise_applies_feedback_then_rechecks_and_refreshes_the_pr(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    h.agent.calls.clear()
    h.forge.calls.clear()
    assert h.pipeline().revise("Use a modal to confirm delete") is None
    revise = skill_calls(h, "revise")[0]
    assert "Use a modal to confirm delete" in revise
    assert "revised" in h.forge.artifacts["revision-1"]
    for skill in ("test", "review", "docs"):
        assert "revised" in staged(skill_calls(h, skill)[0], "revision-1")
    assert [c[1] for c in h.forge.calls if c[0] == "checkpoint"] == [
        "revise 1: apply owner feedback", "pipeline: test", "pipeline: review", "pipeline: docs",
    ]
    assert h.forge.calls[-1][0] == "finish"


def test_second_revision_gets_the_next_number_and_sees_the_first(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    h.pipeline().revise("one")
    h.pipeline().revise("two")
    assert "revision-2" in h.forge.artifacts
    assert "revised" in staged(skill_calls(h, "revise")[1], "revision-1")


def test_blocked_revise_stops_before_rechecking(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    h.agent.calls.clear()
    h.queued["revise"] = ["Status: blocked - feedback too vague"]
    assert h.pipeline().revise("make it nicer") == "revise"
    assert "revise.blocked" in h.forge.artifacts and not h.forge.has_artifact("revision-1")
    assert not skill_calls(h, "test")


def test_declining_gate_b_with_feedback_runs_revise_and_asks_again(tmp_path):
    answers = iter([False, True])
    h = Harness(tmp_path, answers=lambda q: next(answers) if "Mark the PR" in q else True, ask=lambda p: "modal please" if "What should change" in p else "sqlite")
    assert h.pipeline().run() is None
    assert "modal please" in skill_calls(h, "revise")[0]
    assert h.forge.calls[-1][0] == "finish"



def test_revise_works_on_a_run_that_stopped_before_test(tmp_path):
    h = Harness(tmp_path)
    h.queued["test"] = ["Status: fail\nflaky"]
    assert h.pipeline().run() == "test"
    h.agent.calls.clear()
    assert h.pipeline().revise("Use a modal") is None
    revise = skill_calls(h, "revise")[0]
    assert "flaky" in staged(revise, "test.blocked") and "phase-1-summary" in revise
    assert h.forge.has_artifact("test-report") and h.forge.has_artifact("pr")


RULE = "Destructive actions confirm in a modal, never inline."
CONVENTION_REVISION = f"Status: done\n- **Proposed convention** — {RULE}"


def revise_with_convention(tmp_path, answer, existing=None):
    tmp_path.mkdir(exist_ok=True)
    h = Harness(tmp_path, answers=lambda q: answer if "Append it" in q else True)
    h.pipeline().run()
    h.queued["revise"] = [CONVENTION_REVISION]
    h.shown.clear()
    path = h.run_dir.repo / "UX_CONVENTIONS.md"
    if existing is not None:
        path.write_text(existing)
    h.pipeline().revise("Use a modal to confirm delete")
    return h, path


def test_revise_appends_a_confirmed_convention(tmp_path):
    h, path = revise_with_convention(tmp_path / "run", True, existing="- Toasts for success.")
    assert path.read_text() == f"- Toasts for success.\n- {RULE}\n"
    assert any(RULE in message for message in h.shown)


def test_revise_creates_the_conventions_file_when_missing(tmp_path):
    _, path = revise_with_convention(tmp_path, True)
    assert path.read_text() == f"- {RULE}\n"


def test_revise_leaves_the_file_alone_when_the_convention_is_declined(tmp_path):
    _, path = revise_with_convention(tmp_path, False)
    assert not path.exists()


def test_revise_does_not_ask_when_there_is_no_convention_or_it_is_already_listed(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    h.queued["revise"] = ["Status: done\n- **Proposed convention** — None."]
    h.pipeline().revise("one-off")
    assert not any("Append it" in q for q in h.questions)
    h, _ = revise_with_convention(tmp_path / "again", True, existing=f"- {RULE}\n")
    assert not any("Append it" in q for q in h.questions)


def test_green_ci_runs_no_agent_and_gate_b_finishes_with_the_pr_text(tmp_path):
    h = Harness(tmp_path)
    assert h.pipeline().run() is None
    assert not skill_calls(h, "ci-fix")
    assert h.forge.calls[-1] == ("finish", "content")
    assert any("CI: no failures" in text for text in h.shown)


def test_ci_failure_runs_ci_fix_then_retests_and_lists_the_fix_in_the_pr(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [[Check("lint", "fail", RUN_LINK)], [Check("lint", "pass")]]
    assert h.pipeline().run() is None
    assert h.forge.artifacts["ci-failure"] == "log of lint"
    fix = skill_calls(h, "ci-fix")[0]
    assert "log of lint" in staged(fix, "ci-failure")
    assert "fixed the import order" in h.forge.artifacts["ci-fix-1"]
    assert len(skill_calls(h, "test")) == 2
    commits = [c[1] for c in h.forge.calls if c[0] == "checkpoint"]
    assert commits[-3:] == ["pipeline: docs", "pipeline: fix CI failures", "pipeline: test"]
    body = h.forge.calls[-1][1]
    assert body.startswith("content\n\n## CI fixes\n\n- **Check** lint: fixed the import order")


def test_ci_fix_saying_rerun_reruns_the_checks_without_a_commit_or_retest(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [[Check("e2e", "fail", RUN_LINK)], [Check("e2e", "pass")]]
    h.queued["ci-fix"] = ["Status: rerun\n- **Check** e2e: runner timeout"]
    assert h.pipeline().run() is None
    assert ("rerun", "e2e") in h.forge.calls
    assert len(skill_calls(h, "test")) == 1
    assert ("checkpoint", "pipeline: fix CI failures") not in h.forge.calls


def test_ci_still_failing_after_two_rounds_blocks_before_gate_b(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [[Check("lint", "fail", RUN_LINK)]]
    assert h.pipeline().run() == "ci"
    assert len(skill_calls(h, "ci-fix")) == 2
    assert "ci-fix-2" in h.forge.artifacts
    assert "still failing after 2 fix rounds: lint" in h.forge.artifacts["ci.blocked"]
    assert not any(call[0] == "finish" for call in h.forge.calls)


def test_checks_that_also_fail_on_the_base_branch_are_not_fixed(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [[Check("flaky-main", "fail", RUN_LINK), Check("unit", "pass")]]
    h.forge.on_base = {"flaky-main"}
    assert h.pipeline().run() is None
    assert not skill_calls(h, "ci-fix")
    assert any("flaky-main" in text and "base branch" in text for text in h.shown)


def test_blocked_ci_fix_stops_the_run(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [[Check("deploy", "fail", RUN_LINK)]]
    h.queued["ci-fix"] = ["Status: blocked - needs a secret"]
    assert h.pipeline().run() == "ci-fix"
    assert "needs a secret" in h.forge.artifacts["ci-fix.blocked"]
    assert not any(call[0] == "finish" for call in h.forge.calls)


def test_ci_that_never_finishes_times_out_and_resume_waits_again(tmp_path):
    h = Harness(tmp_path, ci_timeout_s=60)
    h.forge.ci_results = [[Check("build", "pending")]]
    assert h.pipeline().run() == "ci"
    assert "did not finish within 60s" in h.forge.artifacts["ci.blocked"]
    h.forge.ci_results = [[Check("build", "pass")]]
    assert h.pipeline().run() is None


def test_ci_waits_for_the_pushed_head_and_for_pending_checks(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [None, [Check("build", "pending")], [Check("build", "pass")]]
    assert h.pipeline().run() is None
    assert h.clock.sleeps == [15, 15]


def test_no_checks_are_accepted_only_after_the_grace_period(tmp_path):
    h = Harness(tmp_path)
    h.forge.ci_results = [[]]
    assert h.pipeline().run() is None
    assert sum(h.clock.sleeps) >= 120
    assert any("No CI checks reported" in text for text in h.shown)


def test_revise_waits_for_ci_before_asking_gate_b_again(tmp_path):
    h = Harness(tmp_path)
    h.pipeline().run()
    h.agent.calls.clear()
    h.forge.calls.clear()
    h.forge.ci_results = [[Check("lint", "fail", RUN_LINK)], [Check("lint", "pass")]]
    assert h.pipeline().revise("Use a modal") is None
    assert len(skill_calls(h, "ci-fix")) == 1
    assert h.forge.calls[-1][0] == "finish"
