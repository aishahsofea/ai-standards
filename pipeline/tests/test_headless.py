from pipeline.checks import CheckRun
from pipeline.owner import HeadlessOwner
from test_stages import ANALYSIS, DECISIONS, RULE, CONVENTION_REVISION, Harness, skill_calls

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
