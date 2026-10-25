import json
import subprocess
from pathlib import Path

import pytest

from pipeline.forge import FakeForge, ForgeError, GitHubForge, Issue, RunState, fetch_issue


class Shell:
    def __init__(self, **outputs):
        self.outputs = outputs
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        key = " ".join(command[:3])
        output = next((v for k, v in self.outputs.items() if key.startswith(k.replace("_", " "))), "")
        output = output() if callable(output) else output
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
    forge, shell, state = make(
        git_diff="x", gh_repo="main", git_rev="2", gh_pr="https://github.com/o/r/pull/9"
    )
    state.issue_url = "https://github.com/o/r/issues/7"
    forge.checkpoint("pipeline: issue")
    forge.checkpoint("pipeline: analyze")
    assert shell.ran("git", "commit", "-m", "pipeline: issue")
    assert len(shell.ran("git", "push", "-u", "origin", "agent/add-dark-mode")) == 2
    assert len(shell.ran("gh", "pr", "create", "--draft")) == 1
    assert state.pr_url == "https://github.com/o/r/pull/9"
    assert not shell.ran("gh", "issue", "comment")
    assert shell.ran("git", "rev-list", "--count", "origin/main..HEAD")


def test_checkpoint_excludes_run_state_from_commits(make):
    forge, shell, _ = make()
    forge.checkpoint("plan")
    assert shell.ran("git", "add", "-A", "--", ".", ":!.agent/runs")


def test_checkpoint_skips_commit_when_nothing_staged(make):
    forge, shell, state = make()
    state.pr_url = "https://github.com/o/r/pull/9"
    forge.checkpoint("test")
    assert not shell.ran("git", "commit")


def test_checkpoint_waits_for_real_commits_before_opening_pr(make):
    forge, shell, state = make(gh_repo="main", git_rev="0")
    forge.checkpoint("analyze")
    assert not shell.ran("gh", "pr", "create")
    assert state.pr_url == ""


def test_start_branch_ignores_run_state_files(make):
    forge, shell, _ = make()
    forge.start_branch()
    assert shell.ran("git", "status", "--porcelain", "--", ".", ":!.agent/runs")


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


def test_fetch_issue_parses_gh_json(make):
    _, shell, _ = make(gh_issue='{"title": "Add dark mode", "body": "Details", "url": "https://github.com/o/r/issues/7"}')
    issue = fetch_issue(Path("."), "7")
    assert issue == Issue("Add dark mode", "Details", "https://github.com/o/r/issues/7")
    assert issue.number == "7"
    assert issue.markdown == "# Add dark mode\n\nDetails\n"
    assert shell.ran("gh", "issue", "view", "7")


ISSUE_URL = "https://github.com/o/r/issues/7"


def comment(name, text="body", id=101):
    body = f"<!-- pipeline:artifact={name} -->\n\n## {name.title()}\n\n{text}" if name else text
    return {"url": f"{ISSUE_URL}#issuecomment-{id}", "body": body}


@pytest.fixture
def issue_forge(make):
    comments: list[dict] = []

    def view():
        return json.dumps({"title": "Add dark mode", "body": "Details", "url": ISSUE_URL, "comments": comments})

    forge, shell, state = make(gh_issue_view=view)
    state.issue_url = ISSUE_URL
    return forge, shell, comments


def test_post_artifact_comments_with_marker_and_heading(issue_forge):
    forge, shell, _ = issue_forge
    forge.post_artifact("decisions", "the text")
    (command,) = shell.ran("gh", "issue", "comment")
    assert command[3] == ISSUE_URL
    assert command[-1] == "<!-- pipeline:artifact=decisions -->\n\n## Decisions\n\nthe text"


def test_has_and_read_artifact_after_post_use_fresh_comments(issue_forge):
    forge, _, comments = issue_forge
    assert not forge.has_artifact("plan")
    forge.post_artifact("plan", "# Plan")
    comments.append(comment("plan", "# Plan"))
    assert forge.has_artifact("plan")
    assert forge.read_artifact("plan") == "# Plan"
    assert forge.read_artifact("analysis") is None


def test_repost_edits_comment_in_place(issue_forge):
    forge, shell, comments = issue_forge
    comments.append(comment("cost", "old", id=555))
    forge.post_artifact("cost", "new")
    assert not shell.ran("gh", "issue", "comment")
    (patch,) = shell.ran("gh", "api")
    assert patch[3:5] == ("PATCH", "repos/o/r/issues/comments/555")
    assert patch[-1] == "body=<!-- pipeline:artifact=cost -->\n\n## Cost\n\nnew"


def test_comment_list_is_cached_between_lookups(issue_forge):
    forge, shell, comments = issue_forge
    comments.append(comment("plan"))
    forge.has_artifact("plan")
    forge.read_artifact("plan")
    forge.has_artifact("analysis")
    assert len(shell.ran("gh", "issue", "view")) == 1
    forge.post_artifact("analysis", "x")
    forge.has_artifact("analysis")
    assert len(shell.ran("gh", "issue", "view")) == 2


def test_oversize_comment_names_the_artifact(issue_forge):
    forge, shell, _ = issue_forge
    with pytest.raises(ForgeError, match="'plan'.*65536"):
        forge.post_artifact("plan", "x" * 65_536)
    assert not shell.ran("gh", "issue", "comment")


def test_comment_at_the_limit_is_accepted(issue_forge):
    forge, shell, _ = issue_forge
    prefix = len("<!-- pipeline:artifact=plan -->\n\n## Plan\n\n")
    forge.post_artifact("plan", "x" * (65_536 - prefix))
    assert shell.ran("gh", "issue", "comment")


def test_issue_artifact_is_the_issue_body(issue_forge):
    forge, _, _ = issue_forge
    assert forge.has_artifact("issue")
    assert forge.read_artifact("issue") == "# Add dark mode\n\nDetails\n"


def test_no_issue_yet_means_no_artifacts(make):
    forge, shell, _ = make()
    assert not forge.has_artifact("issue")
    assert not forge.has_artifact("plan")
    assert forge.read_artifact("plan") is None
    assert not shell.ran("gh", "issue", "view")
    with pytest.raises(ForgeError, match="no issue"):
        forge.post_artifact("plan", "x")


def test_read_artifact_survives_a_human_dropping_the_heading(issue_forge):
    forge, _, comments = issue_forge
    comments.append({"url": f"{ISSUE_URL}#issuecomment-1", "body": "<!-- pipeline:artifact=decisions -->\n## Escalated\nanswered"})
    assert forge.read_artifact("decisions") == "## Escalated\nanswered"


def test_human_comments_after_an_artifact(issue_forge):
    forge, _, comments = issue_forge
    comments += [
        comment(None, "early chatter", 1), comment("decisions", id=2),
        comment("plan", id=3), comment(None, "use sqlite", 4),
    ]
    assert forge.human_comments_after("decisions") == ["use sqlite"]
    assert forge.human_comments_after("analysis") == []


def test_fake_forge_round_trip_and_validation():
    forge = FakeForge()
    forge.post_artifact("plan", "p")
    forge.post_artifact("plan", "q")
    assert (forge.read_artifact("plan"), forge.has_artifact("plan"), forge.has_artifact("pr")) == ("q", True, False)
    assert forge.posts == ["plan", "plan"]
    with pytest.raises(ForgeError, match="'pr'"):
        forge.post_artifact("pr", "x" * 70_000)


def test_reads_retry_transient_failures(make, monkeypatch):
    monkeypatch.setattr("pipeline.forge.time.sleep", lambda _: None)
    replies = iter([None, None, '{"title": "T", "body": "B", "url": "u"}'])
    _, shell, _ = make(gh_issue=lambda: next(replies))
    assert fetch_issue(Path("."), "7") == Issue("T", "B", "u")
    assert len(shell.ran("gh", "issue", "view")) == 3


def test_reads_give_up_after_retries(make, monkeypatch):
    monkeypatch.setattr("pipeline.forge.time.sleep", lambda _: None)
    _, shell, _ = make(gh_issue=None)
    with pytest.raises(ForgeError, match="gh issue view failed"):
        fetch_issue(Path("."), "7")
    assert len(shell.ran("gh", "issue", "view")) == 3


def test_writes_are_not_retried(make):
    forge, shell, _ = make(gh_issue=None)
    with pytest.raises(ForgeError, match="gh issue create failed"):
        forge.open_issue("Title", "Body")
    assert len(shell.ran("gh", "issue", "create")) == 1
