from pipeline.forge import comment_body
from pipeline.stats import RunStats, render_stats, run_stats


def issue(number, **artifacts):
    comments = [{"body": comment_body(name.replace("_", "-").replace("-blocked", ".blocked"), text)} for name, text in artifacts.items()]
    return {"number": number, "title": f"Issue {number}", "comments": [{"body": "a human reply"}, *comments]}


def test_run_stats_reads_blocked_stages_revisions_and_cost():
    stats = run_stats(issue(
        7, analysis="a", implement_phase_2_blocked="Status: blocked - no Node\nmore", test_blocked="Status: fail\n\nNine tests fail on main.",
        revision_1="r", revision_2="r", cost="| stage |\n\nTotal: $3.5000 of $15.00 budget",
    ))
    assert stats == RunStats(7, "Issue 7", {"implement-phase-2": "Status: blocked - no Node", "test": "Status: fail: Nine tests fail on main."}, 2, 3.5)


def test_render_counts_runs_by_stopped_stage():
    runs = [
        run_stats(issue(1, implement_phase_1_blocked="Status: blocked - x", implement_phase_3_blocked="Status: blocked - y")),
        run_stats(issue(2, test_blocked="Status: fail")),
        run_stats(issue(3, analysis="a")),
    ]
    text = render_stats(runs)
    assert "3 runs, 2 stopped at least once, $0.00 spent." in text
    assert "- implement-phase: 1" in text and "- test: 1" in text
    assert "- #1 implement-phase-3: Status: blocked - y" in text
    assert "| #3 Issue 3 | - | 0 | $0.00 |" in text


def test_render_with_no_runs():
    assert render_stats([]) == "No pipeline runs found."
