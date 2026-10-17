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


def test_stage_inputs_are_written_outside_the_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run = RunDir(repo, "feat")
    paths = run.stage_inputs({"plan": "the plan", "phase-1-summary": "done"})
    assert [path.name for path in paths] == ["plan.md", "phase-1-summary.md"]
    assert paths[0].read_text() == "the plan"
    assert all(repo not in path.parents for path in paths)
    run.close()
    assert not paths[0].exists()


def test_stage_inputs_overwrite_earlier_text(tmp_path):
    run = RunDir(tmp_path, "feat")
    run.stage_inputs({"decisions": "old"})
    (path,) = run.stage_inputs({"decisions": "edited"})
    assert path.read_text() == "edited"
    run.close()


@pytest.mark.parametrize("name", ["bogus", "bogus.blocked", "../plan"])
def test_unknown_artifact_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        RunDir(tmp_path, "feat").stage_inputs({name: "x"})


@pytest.mark.parametrize(
    "name", ["issue", "cost", "phase-12-summary", "implement-phase-2.blocked", "analyze.blocked"]
)
def test_known_artifact_names_accepted(tmp_path, name):
    run = RunDir(tmp_path, "feat")
    run.stage_inputs({name: "x"})
    run.close()


def test_state_path_is_in_run_dir(tmp_path):
    run = RunDir(tmp_path, "feat")
    assert run.state_path == run.path / "state.json"
