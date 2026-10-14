import subprocess

import pytest

from pipeline.forge import ForgeError, GitHubForge, RunState


class Shell:
    def __init__(self, **outputs):
        self.outputs = outputs
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        key = " ".join(command[:3])
        output = next((v for k, v in self.outputs.items() if key.startswith(k.replace("_", " "))), "")
        returncode, stdout = (1, "") if output is None else (0, output)
        return subprocess.CompletedProcess(command, returncode, stdout, "nope" if returncode else "")

    def ran(self, *prefix):
        return [c for c in self.commands if c[: len(prefix)] == prefix]


@pytest.fixture
def make(tmp_path, monkeypatch):
    def build(**outputs):
        shell = Shell(**outputs)
        monkeypatch.setattr(subprocess, "run", shell)
        state = RunState("Add dark mode")
        return GitHubForge(tmp_path, "add-dark-mode", state, tmp_path / "state.json"), shell, state

    return build


def test_start_branch_creates_agent_branch_from_clean_tree(make):
    forge, shell, _ = make()
    forge.start_branch()
    assert shell.ran("git", "checkout", "-b", "agent/add-dark-mode")


def test_start_branch_refuses_dirty_tree(make):
    forge, _, _ = make(git_status=" M file.py")
    with pytest.raises(ForgeError, match="uncommitted"):
        forge.start_branch()


def test_start_branch_reuses_existing_branch(make):
    forge, shell, _ = make(git_branch="  agent/add-dark-mode")
    forge.start_branch()
    assert shell.ran("git", "checkout", "agent/add-dark-mode")
    assert not shell.ran("git", "checkout", "-b")


def test_open_issue_saves_url_and_runs_once(make):
    forge, shell, state = make(gh_issue="https://github.com/o/r/issues/7")
    forge.open_issue("Title", "Body")
    forge.open_issue("Title", "Body")
    assert state.issue_url == "https://github.com/o/r/issues/7"
    assert len(shell.ran("gh", "issue", "create")) == 1
    assert RunState.load(forge.state_path) == state


def test_checkpoint_commits_pushes_and_opens_draft_pr_once(make):
    forge, shell, state = make(git_status=" M x", gh_pr="https://github.com/o/r/pull/9")
    state.issue_url = "https://github.com/o/r/issues/7"
    forge.checkpoint("issue")
    forge.checkpoint("analyze")
    assert shell.ran("git", "commit", "-m", "pipeline: issue")
    assert len(shell.ran("git", "push", "-u", "origin", "agent/add-dark-mode")) == 2
    assert len(shell.ran("gh", "pr", "create", "--draft")) == 1
    assert state.pr_url == "https://github.com/o/r/pull/9"
    assert "pull/9" in shell.ran("gh", "issue", "comment")[0][-1]


def test_checkpoint_skips_commit_when_nothing_changed(make):
    forge, shell, state = make()
    state.pr_url = "https://github.com/o/r/pull/9"
    forge.checkpoint("test")
    assert not shell.ran("git", "commit")


def test_finish_updates_body_and_marks_ready(make):
    forge, shell, state = make()
    state.pr_url, state.issue_url = "https://github.com/o/r/pull/9", "https://github.com/o/r/issues/7"
    forge.finish("PR text")
    edit = shell.ran("gh", "pr", "edit")[0]
    assert edit[-1] == "PR text\n\nCloses https://github.com/o/r/issues/7"
    assert shell.ran("gh", "pr", "ready", "https://github.com/o/r/pull/9")


def test_command_failure_raises(make):
    forge, _, _ = make(git_add=None)
    with pytest.raises(ForgeError, match="nope"):
        forge.checkpoint("issue")
