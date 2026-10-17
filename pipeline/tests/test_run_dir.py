import pytest

from pipeline.run_dir import RunDir, slugify


def test_slugify_normalizes_idea():
    assert slugify("  Add Dark-Mode toggle!! ") == "add-dark-mode-toggle"


def test_slugify_truncates_without_trailing_dash():
    slug = slugify("word " * 30)
    assert len(slug) <= 50
    assert not slug.endswith("-")


def test_slugify_rejects_empty():
    with pytest.raises(ValueError):
        slugify("!!!")


def test_creates_run_dir_under_agent_runs(tmp_path):
    run = RunDir.from_idea(tmp_path, "Add dark mode")
    assert run.path == tmp_path / ".agent" / "runs" / "add-dark-mode"
    assert run.path.is_dir()


def test_artifact_round_trip(tmp_path):
    run = RunDir(tmp_path, "feat")
    path = run.artifact_path("analysis")
    assert not run.exists(path)
    run.write(path, "findings")
    assert run.exists(path)
    assert run.read(path) == "findings"
    assert path.name == "analysis.md"


def test_reopening_keeps_artifacts(tmp_path):
    RunDir(tmp_path, "feat").write(RunDir(tmp_path, "feat").artifact_path("plan"), "p")
    again = RunDir(tmp_path, "feat")
    assert again.read(again.artifact_path("plan")) == "p"


def test_unknown_artifact_rejected(tmp_path):
    with pytest.raises(ValueError):
        RunDir(tmp_path, "feat").artifact_path("bogus")


def test_phase_summary_path(tmp_path):
    assert RunDir(tmp_path, "feat").phase_summary_path(2).name == "phase-2-summary.md"


def test_phase_zero_rejected(tmp_path):
    with pytest.raises(ValueError):
        RunDir(tmp_path, "feat").phase_summary_path(0)
