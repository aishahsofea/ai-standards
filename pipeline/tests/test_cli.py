import json

import pytest

from pipeline import cli
from pipeline.agent import AgentError, FakeAgent
from pipeline.cost import BudgetExceeded
from pipeline.cli import main
from pipeline.forge import FakeForge, Issue, RunState
from pipeline.run_dir import run_lock


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


@pytest.mark.parametrize("argv", [["run"], ["run", "idea", "--resume", "slug"], ["run", "--resume", "s", "--dry-run"], ["run", "idea", "--dry-run", "--worktree"]])
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
    monkeypatch.setattr(cli, "notify", lambda _: None)
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
    assert "Total: $1.5000" in fake_github.artifacts["cost"]


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
    assert built[0][7] == {"PIPELINE_EVIDENCE_DIR": str(tmp_path / ".agent" / "runs" / "add-dark-mode" / "evidence")}


def test_worktree_run_works_there_and_a_resume_returns_to_it(tmp_path, monkeypatch, fake_github):
    work = tmp_path / "wt"
    work.mkdir()
    created, built = [], []
    monkeypatch.setattr(cli, "create_worktree", lambda repo, slug, env: created.append(slug) or work)
    monkeypatch.setattr(cli, "ClaudeAgent", lambda *args: built.append(args) or FakeAgent(cli.dry_run_text))
    repo = tmp_path / "repo"
    repo.mkdir()
    main(["run", "Add dark mode", "--repo", str(repo), "--worktree", "--stop-after", "issue"])
    assert RunState.load(repo / ".agent" / "runs" / "add-dark-mode" / "state.json").worktree == str(work)
    main(["run", "--resume", "add-dark-mode", "--repo", str(repo), "--stop-after", "analyze"])
    assert created == ["add-dark-mode"]
    assert {args[0] for args in built} == {work}


def test_a_missing_worktree_is_an_error(tmp_path, monkeypatch, fake_github, capsys):
    monkeypatch.setattr(cli, "create_worktree", lambda repo, slug, env: tmp_path / "gone")
    assert run_in(tmp_path, "--worktree") == 1
    assert "is missing" in capsys.readouterr().err


def test_revise_unknown_run_fails_cleanly(tmp_path, capsys):
    assert main(["revise", "nothing", "make it a modal", "--repo", str(tmp_path)]) == 1
    assert "no run 'nothing'" in capsys.readouterr().err


def test_headless_run_waits_on_the_owner_with_exit_3(capsys):
    assert main(["run", "Add dark mode", "--dry-run", "--headless"]) == 3
    out = capsys.readouterr().out
    assert "Waiting on the owner" in out and "request-plan" in out and "--headless" in out


def test_headless_cannot_combine_with_step():
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "idea", "--headless", "--step"])
    assert exit_info.value.code == 2


def no_stdin(monkeypatch):
    def fail(*_):
        raise AssertionError("headless mode read the terminal")

    monkeypatch.setattr("builtins.input", fail)
    monkeypatch.setattr(cli, "confirm", fail)
    monkeypatch.setattr(cli, "notify", fail)


def test_headless_run_continues_from_replies_and_finishes_with_exit_0(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text))
    no_stdin(monkeypatch)
    assert run_in(tmp_path, "--headless") == 3
    fake_github.reply("/approve")
    resume = ["run", "--resume", "add-dark-mode", "--repo", str(tmp_path), "--headless"]
    assert main(resume) == 3
    assert "request-gate-b" in capsys.readouterr().out
    fake_github.reply("/approve")
    assert main(resume) == 0
    assert fake_github.calls[-1][0] == "finish"


def test_headless_run_passes_allow_replies_to_the_agent(tmp_path, monkeypatch, fake_github):
    built = []
    monkeypatch.setattr(cli, "ClaudeAgent", lambda *args: built.append(args) or FakeAgent(cli.dry_run_text))
    fake_github.reply("/allow Bash(docker ps:*)")
    run_in(tmp_path, "--headless", "--stop-after", "issue")
    assert "Bash(docker ps:*)" in built[0][6]


def test_headless_stop_that_is_not_a_wait_exits_0(tmp_path, monkeypatch, fake_github):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "Status: blocked - nope"))
    assert run_in(tmp_path, "--headless") == 0


def test_headless_revise_waits_at_gate_b(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "Status: done\nrevised" if "/revise/SKILL.md" in prompt else cli.dry_run_text(prompt)))
    no_stdin(monkeypatch)
    run_in(tmp_path, "--headless")
    fake_github.reply("/approve")
    assert main(["run", "--resume", "add-dark-mode", "--repo", str(tmp_path), "--headless"]) == 3
    assert main(["revise", "add-dark-mode", "Use a modal", "--repo", str(tmp_path), "--headless"]) == 3
    assert "revision-1" in fake_github.artifacts and "request-gate-b" in capsys.readouterr().out


def last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_json_reports_what_the_issue_has_cost(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text, cost_usd=0.5))
    run_in(tmp_path, "--json", "--stop-after", "analyze")
    assert last_json(capsys)["spent_usd"] == 1.0
    main(["run", "--resume", "add-dark-mode", "--repo", str(tmp_path), "--stop-after", "decide", "--json"])
    assert last_json(capsys)["spent_usd"] == 1.5


def test_json_reports_a_wait_with_its_stage_and_request(capsys):
    assert main(["run", "Add dark mode", "--dry-run", "--headless", "--json"]) == 3
    assert last_json(capsys) == {"status": "waiting", "stage": "plan", "request": "plan", "spent_usd": 0.0}


def test_json_reports_a_finished_run(capsys):
    assert main(["run", "Add dark mode", "--dry-run", "--json"]) == 0
    assert last_json(capsys) == {"status": "finished", "stage": None, "request": None, "spent_usd": 0.0}


def test_json_reports_a_stop(capsys):
    assert main(["run", "Add dark mode", "--dry-run", "--stop-after", "plan", "--json"]) == 0
    assert last_json(capsys) == {"status": "stopped", "stage": "plan", "request": None, "spent_usd": 0.0}


def test_json_reports_a_blocked_stage_as_stopped(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "Status: blocked - nope"))
    assert run_in(tmp_path, "--headless", "--json") == 0
    assert last_json(capsys) == {"status": "stopped", "stage": "issue", "request": None, "spent_usd": 0.0}


def test_json_is_the_last_line_of_a_revise(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "Status: done\nrevised" if "/revise/SKILL.md" in prompt else cli.dry_run_text(prompt)))
    run_in(tmp_path, "--headless")
    fake_github.reply("/approve")
    main(["run", "--resume", "add-dark-mode", "--repo", str(tmp_path), "--headless"])
    capsys.readouterr()
    assert main(["revise", "add-dark-mode", "Use a modal", "--repo", str(tmp_path), "--headless", "--json"]) == 3
    assert last_json(capsys) == {"status": "waiting", "stage": "docs", "request": "gate-b", "spent_usd": 0.0}


def test_no_json_line_without_the_flag(capsys):
    main(["run", "Add dark mode", "--dry-run"])
    assert not capsys.readouterr().out.strip().endswith("}")


def test_a_second_process_on_the_same_run_is_refused(tmp_path, monkeypatch, fake_github, capsys):
    use_agent(monkeypatch, FakeAgent(cli.dry_run_text))
    with run_lock(tmp_path, "add-dark-mode"):
        assert run_in(tmp_path) == 1
    assert "already running" in capsys.readouterr().err
    assert run_in(tmp_path) == 0


def test_the_lock_is_per_run(tmp_path):
    with run_lock(tmp_path, "one"), run_lock(tmp_path, "two"):
        pass


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_events_flag_appends_one_json_object_per_line(tmp_path, capsys):
    events = tmp_path / "run.events.jsonl"
    events.write_text('{"event": "earlier"}\n')
    assert main(["run", "Add dark mode", "--dry-run", "--events", str(events)]) == 0
    lines = read_events(events)
    assert lines[0] == {"event": "earlier"}
    assert {"stage-started", "stage-finished", "plan-posted", "ci-green"} <= {line["event"] for line in lines}
    assert all(set(line) == {"event", "stage", "detail", "timestamp"} for line in lines[1:])


def test_without_the_events_flag_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["run", "Add dark mode", "--dry-run"]) == 0
    assert not list(tmp_path.rglob("*.jsonl"))


def test_a_blocked_stage_is_an_event(tmp_path, monkeypatch, fake_github):
    use_agent(monkeypatch, FakeAgent(lambda prompt: "Status: blocked - nope", cost_usd=0.5))
    events = tmp_path / "events.jsonl"
    assert run_in(tmp_path, "--events", str(events)) == 0
    assert [(line["event"], line["stage"]) for line in read_events(events)][-1] == ("blocked", "issue")


def test_waiting_and_a_deliberate_stop_are_not_blocked(tmp_path):
    events = tmp_path / "events.jsonl"
    assert main(["run", "Add dark mode", "--dry-run", "--stop-after", "plan", "--events", str(events)]) == 0
    assert "blocked" not in {line["event"] for line in read_events(events)}


def test_revise_accepts_events(tmp_path):
    assert main(["revise", "x", "fb", "--repo", str(tmp_path), "--events", str(tmp_path / "e.jsonl")]) == 1
