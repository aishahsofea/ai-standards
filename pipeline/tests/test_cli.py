import pytest

from pipeline import cli
from pipeline.agent import AgentError, FakeAgent
from pipeline.cost import BudgetExceeded
from pipeline.cli import main
from pipeline.forge import FakeForge, Issue, RunState


def test_dry_run_finishes_end_to_end(capsys):
    assert main(["run", "Add dark mode", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Finished;" in out
    assert "spent $0.00" in out


def test_dry_run_stop_after_prints_resume_hint(capsys):
    assert main(["run", "Add dark mode", "--dry-run", "--stop-after", "plan"]) == 0
    out = capsys.readouterr().out
    assert "Stopped at 'plan'" in out
    assert "--resume add-dark-mode" in out


@pytest.mark.parametrize("argv", [["run"], ["run", "idea", "--resume", "slug"], ["run", "--resume", "s", "--dry-run"]])
def test_bad_arguments_exit_with_usage_error(argv):
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_resume_unknown_run_fails_cleanly(tmp_path, capsys):
    assert main(["run", "--resume", "nothing", "--repo", str(tmp_path)]) == 1
    assert "no run 'nothing'" in capsys.readouterr().err


@pytest.fixture
def fake_github(tmp_path, monkeypatch):
    forge = FakeForge()
    monkeypatch.setattr(cli, "GitHubForge", lambda *args: forge)
    monkeypatch.setattr(cli, "confirm", lambda _: True)
    return forge


def use_agent(monkeypatch, agent):
    monkeypatch.setattr(cli, "ClaudeAgent", lambda *args: agent)


def run_in(tmp_path, *extra):
    return main(["run", "Add dark mode", "--repo", str(tmp_path), *extra])


def test_issue_run_skips_issue_creation_and_commits_no_run_files(tmp_path, monkeypatch, fake_github):
    issue = Issue("Add dark mode", "Details", "https://github.com/o/r/issues/7")
    fake_github.artifacts["issue"] = issue.markdown
    monkeypatch.setattr(cli, "fetch_issue", lambda repo, ref: issue)
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text))

    assert main(["run", "--issue", "7", "--repo", str(tmp_path)]) == 0

    run_dir = tmp_path / ".agent" / "runs" / "7-add-dark-mode"
    assert RunState.load(run_dir / "state.json").issue_url == issue.url
    assert ("open_issue", "Add dark mode") not in fake_github.calls
    assert not list(run_dir.glob("*.md"))


def test_cost_comment_posted_on_clean_finish(tmp_path, monkeypatch, fake_github):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text, cost_usd=0.5))
    assert run_in(tmp_path) == 0
    cost = fake_github.artifacts["cost"]
    assert "| analyze | opus | 0.5000 |" in cost
    assert "Total: $4.0000 of $15.00 budget" in cost
    assert fake_github.posts[-1] == "cost"


def test_cost_comment_posted_when_stopped_at_a_gate(tmp_path, monkeypatch, fake_github):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text, cost_usd=0.5))
    monkeypatch.setattr(cli, "confirm", lambda _: False)
    run_in(tmp_path)
    assert "Total: $0.5000" in fake_github.artifacts["cost"]


def test_cost_comment_posted_when_a_stage_is_blocked(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "Status: blocked - nope", cost_usd=0.5))
    assert run_in(tmp_path) == 0
    assert "Total: $0.5000" in fake_github.artifacts["cost"]
    assert "issue.blocked" in fake_github.artifacts
    assert "Stopped at 'issue'" in capsys.readouterr().out


def test_cost_comment_posted_when_budget_is_exceeded(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text, cost_usd=0.6))
    monkeypatch.setenv("BUDGET_USD", "1.0")
    assert run_in(tmp_path) == 1
    assert "over the $1.00 budget" in capsys.readouterr().err
    assert "Total: $1.2000 of $1.00 budget" in fake_github.artifacts["cost"]


def test_cost_comment_posted_when_the_agent_fails(tmp_path, monkeypatch, fake_github, capsys):
    def explode(prompt):
        raise AgentError("claude timed out")

    use_agent(monkeypatch, FakeAgent(explode))
    assert run_in(tmp_path) == 1
    assert "claude timed out" in capsys.readouterr().err
    assert "cost" in fake_github.artifacts


def test_failed_cost_post_prints_table_and_keeps_original_error(tmp_path, monkeypatch, fake_github, capsys):
    def no_post(name, text):
        raise cli.ForgeError("gh down")

    fake_github.post_artifact = no_post
    def explode(prompt):
        raise AgentError("agent broke")

    use_agent(monkeypatch, FakeAgent(explode))
    assert run_in(tmp_path) == 1
    err = capsys.readouterr().err
    assert "agent broke" in err
    assert "gh down" in err
    assert "| stage | model | cost_usd |" in err


def test_second_run_edits_cost_comment_and_resume_starts_from_prior_total(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text, cost_usd=0.5))
    assert run_in(tmp_path, "--stop-after", "analyze") == 0
    assert "Total: $1.0000" in fake_github.artifacts["cost"]

    assert main(["run", "--resume", "add-dark-mode", "--repo", str(tmp_path), "--stop-after", "decide"]) == 0
    cost = fake_github.artifacts["cost"]
    assert fake_github.posts.count("cost") == 2
    assert "| earlier runs | - | 1.0000 |" in cost
    assert "Total: $1.5000" in cost
    assert "spent $1.50" in capsys.readouterr().out


def test_resume_budget_covers_the_whole_issue(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text, cost_usd=0.5))
    run_in(tmp_path, "--stop-after", "analyze")
    monkeypatch.setenv("BUDGET_USD", "1.0")
    with pytest.raises(BudgetExceeded):
        cli.run_pipeline(cli.build_parser().parse_args(["run", "--resume", "add-dark-mode", "--repo", str(tmp_path)]))


def test_issue_cannot_combine_with_idea_or_dry_run():
    for argv in (["run", "idea", "--issue", "7"], ["run", "--issue", "7", "--dry-run"]):
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2


def test_eval_subcommand_prints_score_and_fails_on_bad_output(monkeypatch, capsys):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "nothing useful", cost_usd=0.1))
    assert main(["eval", "--case", "public-api"]) == 1
    out = capsys.readouterr().out
    assert "FAIL public-api" in out and "Score: 0/1" in out


def test_real_agent_may_read_skills_and_staged_inputs(tmp_path, monkeypatch, fake_github):
    built = []
    monkeypatch.setattr(cli, "ClaudeAgent", lambda *args: built.append(args) or FakeAgent(cli.dry_run_text))
    run_in(tmp_path, "--stop-after", "issue")
    add_dirs = built[0][4]
    assert cli.SKILLS_DIR in add_dirs and len(add_dirs) == 2


def test_revise_unknown_run_fails_cleanly(tmp_path, capsys):
    assert main(["revise", "nothing", "make it a modal", "--repo", str(tmp_path)]) == 1
    assert "no run 'nothing'" in capsys.readouterr().err
