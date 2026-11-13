import json
import os
import subprocess
import sys

import pytest

from pipeline.forge import ForgeError, GitHubForge, RunState
from pipeline.worktree import create_worktree


def git(repo, *args):
    return subprocess.run(("git", *args), cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "shop"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "base")
    return repo


def configure(repo, **settings):
    (repo / ".pipeline.json").write_text(json.dumps(settings))


def test_worktree_is_on_the_run_branch_and_leaves_the_checkout_alone(repo, tmp_path):
    (repo / "app.py").write_text("x = 2  # uncommitted\n")
    path = create_worktree(repo, "feat", dict(os.environ), tmp_path / "wt")
    assert path == tmp_path / "wt" / "shop" / "feat"
    assert git(path, "branch", "--show-current") == "agent/feat"
    assert (path / "app.py").read_text() == "x = 1\n"
    assert git(repo, "branch", "--show-current") == "main"


def test_copy_and_setup_prepare_the_worktree(repo, tmp_path):
    (repo / ".env").write_text("KEY=1\n")
    (repo / "data").mkdir()
    (repo / "data" / "seed.txt").write_text("seed")
    configure(repo, copy=[".env", "data"], setup=[f'{sys.executable} -c "open(\'ready\', \'w\').close()"'])
    path = create_worktree(repo, "feat", dict(os.environ), tmp_path / "wt")
    assert (path / ".env").read_text() == "KEY=1\n"
    assert (path / "data" / "seed.txt").read_text() == "seed"
    assert (path / "ready").exists()
    state = RunState("idea")
    GitHubForge(path, "feat", state, tmp_path / "state.json").start_branch()
    assert {".env", "data/seed.txt", "ready"} <= set(state.baseline)


def test_a_failing_setup_command_is_an_error(repo, tmp_path):
    configure(repo, setup=[f'{sys.executable} -c "import sys; print(\'no deps\'); sys.exit(1)"'])
    with pytest.raises(ForgeError, match="no deps"):
        create_worktree(repo, "feat", dict(os.environ), tmp_path / "wt")
    assert not (tmp_path / "wt" / "shop" / "feat").exists()
    assert git(repo, "branch", "--list", "agent/feat") == ""
