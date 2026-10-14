import pytest

from pipeline.cli import main


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
