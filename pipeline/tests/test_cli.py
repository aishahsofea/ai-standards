import pytest

from pipeline import cli
from pipeline.agent import FakeAgent
from pipeline.cli import main
from pipeline.forge import FakeForge, Issue, RunState


def test_dry_run_finishes_end_to_end(capsys):
    assert main(["run", "Add dark mode", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Finished in" in out
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


def test_issue_run_seeds_run_dir_and_skips_issue_creation(tmp_path, monkeypatch, capsys):
    issue = Issue("Add dark mode", "Details", "https://github.com/o/r/issues/7")
    forge = FakeForge()
    monkeypatch.setattr(cli, "fetch_issue", lambda repo, ref: issue)
    monkeypatch.setattr(cli, "GitHubForge", lambda *args: forge)
    monkeypatch.setattr(cli, "ClaudeAgent", lambda *args: FakeAgent(cli.dry_run_text))
    monkeypatch.setattr(cli, "confirm", lambda _: True)

    assert main(["run", "--issue", "7", "--repo", str(tmp_path)]) == 0

    run_dir = tmp_path / ".agent" / "runs" / "7-add-dark-mode"
    assert (run_dir / "issue.md").read_text() == issue.markdown
    assert RunState.load(run_dir / "state.json").issue_url == issue.url
    assert ("open_issue", "Add dark mode") not in forge.calls


def test_issue_cannot_combine_with_idea_or_dry_run():
    for argv in (["run", "idea", "--issue", "7"], ["run", "--issue", "7", "--dry-run"]):
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2
