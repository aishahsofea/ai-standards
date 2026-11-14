from pipeline.agent import Denial, FakeAgent, Result
from pipeline.checks import CheckRun
from pipeline.owner import HeadlessOwner
from test_stages import ANALYSIS, DECISIONS, PLAN, RULE, CONVENTION_REVISION, Harness, skill_calls

ANSWERED = DECISIONS.replace("model?", "model?\n  Answer: sqlite")
FAILING = [CheckRun("pytest", False, "9 failed")]


def headless(tmp_path, **options):
    return Harness(tmp_path, headless=True, **options)


def past_gate_a(tmp_path, *approved):
    """A headless run with Gate A already answered and the named requests already approved."""
    h = headless(tmp_path)
    h.forge.artifacts.update(issue="# T", analysis=ANALYSIS, decisions=ANSWERED)
    for key in approved:
        h.forge.request(key, "asked earlier")
        h.forge.reply("/approve")
    return h


def test_failing_baseline_posts_one_request_and_waits(tmp_path):
    h = headless(tmp_path, checks=lambda: FAILING, stop_after="analyze")
    assert h.pipeline().run() == "preflight"
    assert h.owner.waiting == "baseline"
    request = h.forge.artifacts["request-baseline"]
    assert "9 failed" in request and "/approve" in request
    assert h.pipeline().run() == "preflight"
    assert h.forge.posts.count("request-baseline") == 1 and "baseline" not in h.forge.artifacts


def test_approved_baseline_continues(tmp_path):
    h = headless(tmp_path, checks=lambda: FAILING, stop_after="analyze")
    h.pipeline().run()
    h.forge.reply("/approve")
    assert h.pipeline().run() == "analyze"
    assert "9 failed" in h.forge.artifacts["baseline"] and h.owner.waiting is None


def test_baseline_approval_from_a_non_collaborator_is_ignored(tmp_path):
    h = headless(tmp_path, checks=lambda: FAILING, stop_after="analyze")
    h.pipeline().run()
    h.forge.reply("/approve", "NONE")
    assert h.pipeline().run() == "preflight" and h.owner.waiting == "baseline"


def test_rejected_baseline_stops_without_waiting(tmp_path):
    h = headless(tmp_path, checks=lambda: FAILING, stop_after="analyze")
    h.pipeline().run()
    h.forge.reply("/reject")
    assert h.pipeline().run() == "preflight" and h.owner.waiting is None


def test_plan_posts_one_request_and_waits_even_when_run_again(tmp_path):
    h = past_gate_a(tmp_path)
    assert h.pipeline().run() == "plan"
    assert h.owner.waiting == "plan" and "/approve" in h.forge.artifacts["request-plan"]
    assert h.pipeline().run() == "plan"
    assert h.forge.posts.count("request-plan") == 1 and h.owner.waiting == "plan"
    assert "implement-phase-1" not in h.called_stages()


def test_plan_request_lists_the_commands_approval_allows(tmp_path):
    h = past_gate_a(tmp_path)
    h.plan = "## Commands\n- Phase 1: `pnpm add -D x`\n" + PLAN
    h.pipeline().run()
    assert "- `pnpm add -D x`" in h.forge.artifacts["request-plan"]


def test_approved_plan_continues(tmp_path):
    h = past_gate_a(tmp_path)
    h.pipeline().run()
    h.forge.reply("/approve")
    assert h.pipeline().run() == "docs"
    assert "implement-phase-2" in h.called_stages()


def test_plan_approval_from_a_non_collaborator_is_ignored(tmp_path):
    h = past_gate_a(tmp_path)
    h.pipeline().run()
    h.forge.reply("/approve", "CONTRIBUTOR")
    assert h.pipeline().run() == "plan" and h.owner.waiting == "plan"


def test_rejected_plan_stays_stopped_on_every_run(tmp_path):
    h = past_gate_a(tmp_path)
    h.pipeline().run()
    h.forge.reply("/reject")
    for _ in range(2):
        assert h.pipeline().run() == "plan" and h.owner.waiting is None
    assert "implement-phase-1" not in h.called_stages()


def test_gate_b_posts_one_request_and_waits(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    assert h.pipeline().run() == "docs"
    assert h.owner.waiting == "gate-b" and "Mark the PR ready?" in h.forge.artifacts["request-gate-b"]
    assert h.pipeline().run() == "docs"
    assert h.forge.posts.count("request-gate-b") == 1
    assert all(call[0] != "finish" for call in h.forge.calls)


def test_approved_gate_b_finishes(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.forge.reply("/approve")
    assert h.pipeline().run() is None
    assert h.forge.calls[-1] == ("finish", "content") and h.owner.waiting is None


def test_gate_b_approval_from_a_non_collaborator_is_ignored(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.forge.reply("/approve", "NONE")
    assert h.pipeline().run() == "docs" and h.owner.waiting == "gate-b"


def test_rejected_gate_b_stops_without_finishing_or_waiting(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.forge.reply("/reject")
    assert h.pipeline().run() == "docs" and h.owner.waiting is None
    assert all(call[0] != "finish" for call in h.forge.calls)


def test_a_proposed_convention_is_never_appended_or_requested(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.queued["revise"] = [CONVENTION_REVISION]
    h.forge.reply("/approve")
    h.pipeline().revise("Use a modal to confirm delete")
    assert RULE in h.forge.artifacts["revision-1"]
    assert not (h.run_dir.repo / "UX_CONVENTIONS.md").exists()
    assert not [name for name in h.forge.posts if "convention" in name]


def test_headless_owner_never_reads_the_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("read stdin")))
    h = past_gate_a(tmp_path, "plan")
    assert h.pipeline().run() == "docs"
    assert isinstance(h.owner, HeadlessOwner)


RECOMMENDED = DECISIONS.replace("model?", "model? Recommendation: sqlite, it is already used.")
NONE_ESCALATED = "## Decided from evidence\n- **Q1: data model** - sqlite.\n## Decided, low stakes\nNone.\n## Escalated\nNone.\n"


def decide_calls(h):
    return skill_calls(h, "decide")


def test_gate_a_posts_one_request_and_waits(tmp_path):
    h = headless(tmp_path)
    assert h.pipeline().run() == "decide"
    assert h.owner.waiting == "gate-a" and "Q<n>:" in h.forge.artifacts["request-gate-a"]
    assert h.pipeline().run() == "decide"
    assert h.forge.posts.count("request-gate-a") == 1 and not h.forge.has_artifact("plan")


def test_gate_a_answer_reply_is_written_to_the_decisions_and_the_run_continues(tmp_path):
    h = headless(tmp_path)
    h.pipeline().run()
    h.forge.reply("Thanks.\nQ1: sqlite")
    assert h.pipeline().run() == "plan"
    assert "Answer: sqlite" in h.forge.artifacts["decisions"]
    assert len(decide_calls(h)) == 1 and h.owner.waiting == "plan"


def test_gate_a_answer_from_a_non_collaborator_is_ignored(tmp_path):
    h = headless(tmp_path)
    h.pipeline().run()
    h.forge.reply("Q1: mongodb", "NONE")
    assert h.pipeline().run() == "decide"
    assert h.forge.artifacts["decisions"] == DECISIONS and h.owner.waiting == "gate-a"


def test_gate_a_revisit_reply_reruns_decide(tmp_path):
    h = headless(tmp_path)
    h.queued["decide"] = [DECISIONS, ANSWERED]
    h.pipeline().run()
    h.forge.reply("Q1: !sqlite")
    assert h.pipeline().run() == "plan"
    assert len(decide_calls(h)) == 2 and "remove each '[revisit]'" in decide_calls(h)[1]
    assert h.forge.artifacts["decisions"] == ANSWERED


def test_gate_a_approve_accepts_the_recommendation_for_open_questions(tmp_path):
    h = headless(tmp_path)
    h.queued["decide"] = [RECOMMENDED]
    h.pipeline().run()
    h.forge.reply("/approve")
    assert h.pipeline().run() == "plan"
    assert "Answer: sqlite, it is already used." in h.forge.artifacts["decisions"]


def test_gate_a_approve_still_waits_on_a_question_without_a_recommendation(tmp_path):
    h = headless(tmp_path)
    h.pipeline().run()
    h.forge.reply("/approve")
    assert h.pipeline().run() == "decide" and h.owner.waiting == "gate-a"


def test_gate_a_approval_from_a_non_collaborator_is_ignored(tmp_path):
    h = headless(tmp_path)
    h.queued["decide"] = [RECOMMENDED]
    h.pipeline().run()
    h.forge.reply("/approve", "NONE")
    assert h.pipeline().run() == "decide" and h.forge.artifacts["decisions"] == RECOMMENDED


def test_gate_a_with_nothing_escalated_asks_nothing(tmp_path):
    h = headless(tmp_path)
    h.queued["decide"] = [NONE_ESCALATED]
    assert h.pipeline().run() == "plan"
    assert "request-gate-a" not in h.forge.artifacts


def test_gate_b_request_records_the_head_commit(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.forge.head_commit = "abc123"
    h.pipeline().run()
    assert "abc123" in h.forge.artifacts["request-gate-b"]


def test_gate_b_approval_does_not_apply_after_the_branch_moved(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.forge.reply("/approve")
    h.forge.head_commit = "def456"
    assert h.pipeline().run() == "docs"
    assert h.owner.waiting == "gate-b" and "def456" in h.forge.artifacts["request-gate-b"]
    assert ("withdraw", "gate-b") in h.forge.calls and all(call[0] != "finish" for call in h.forge.calls)
    h.forge.reply("/approve")
    assert h.pipeline().run() is None


def test_gate_b_revise_reply_runs_revise_once_and_asks_again(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.forge.reply("/revise Use a modal\nnot inline")
    assert h.pipeline().run() == "docs"
    (revise,) = skill_calls(h, "revise")
    assert "Use a modal\nnot inline" in revise
    assert h.owner.waiting == "gate-b" and h.forge.has_artifact("request-gate-b")
    assert all(call[0] != "finish" for call in h.forge.calls)
    assert h.pipeline().run() == "docs" and len(skill_calls(h, "revise")) == 1


def test_gate_b_revise_from_a_non_collaborator_is_ignored(tmp_path):
    h = past_gate_a(tmp_path, "plan")
    h.pipeline().run()
    h.forge.reply("/revise delete everything", "NONE")
    assert h.pipeline().run() == "docs"
    assert not skill_calls(h, "revise") and h.owner.waiting == "gate-b"


DOCKER = "Bash(docker ps:*)"


class Denying(FakeAgent):
    """Denies `docker ps` in phase 2 until the rule is allowed; `on_denial` runs at each denial."""

    def __init__(self, h, on_denial=lambda: None):
        super().__init__(h._respond)
        self.h, self.on_denial = h, on_denial

    def run(self, prompt, model, budget, resume=None):
        if "Implement only phase 2" in prompt and DOCKER not in self.h.owner.allowed:
            self.on_denial()
            return Result("Status: blocked - docker was denied", 0.0, (Denial("Bash", "docker ps"),))
        return super().run(prompt, model, budget, resume)


def denied_run(tmp_path, on_denial=lambda: None):
    h = past_gate_a(tmp_path, "plan")
    h.agent = Denying(h, on_denial)
    return h


def test_denied_command_posts_one_request_and_waits(tmp_path):
    h = denied_run(tmp_path)
    assert h.pipeline().run() == "implement-phase-2"
    assert h.owner.waiting == "allow" and f"/allow {DOCKER}" in h.forge.artifacts["request-allow"]
    assert h.forge.has_artifact("implement-phase-2.blocked")
    assert h.pipeline().run() == "implement-phase-2"
    assert h.forge.posts.count("request-allow") == 1


def test_allow_reply_is_loaded_when_the_next_run_starts_and_the_stage_reruns(tmp_path):
    h = denied_run(tmp_path)
    h.pipeline().run()
    h.forge.reply(f"Fine.\n/allow `{DOCKER}`")
    assert h.pipeline().run() == "docs"
    assert h.owner.allowed == [DOCKER] and h.forge.has_artifact("phase-2-summary")
    assert not (tmp_path / ".pipeline.json").exists()


def test_allow_reply_from_a_non_collaborator_is_ignored(tmp_path):
    h = denied_run(tmp_path)
    h.pipeline().run()
    h.forge.reply(f"/allow {DOCKER}", "NONE")
    assert h.pipeline().run() == "implement-phase-2"
    assert h.owner.allowed == [] and h.owner.waiting == "allow"


def test_allow_reply_posted_during_the_run_reruns_the_stage_at_once(tmp_path):
    h = denied_run(tmp_path, on_denial=lambda: h.forge.reply(f"/allow {DOCKER}"))
    assert h.pipeline().run() == "docs"
    assert not h.forge.has_artifact("implement-phase-2.blocked") and "request-allow" not in h.forge.artifacts
