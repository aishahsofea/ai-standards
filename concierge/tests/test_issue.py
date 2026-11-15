import json

import pytest

from concierge.issue import GitHubIssue
from pipeline.forge import RunState


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "wt"
    work.mkdir()
    run = tmp_path / ".agent" / "runs" / "dark"
    run.mkdir(parents=True)
    RunState("idea", "https://github.com/o/r/issues/7", worktree=str(work)).save(run / "state.json")
    return tmp_path, work


def issue_with(repo, output):
    calls = []

    def run(command, cwd, retry=False):
        calls.append((command, cwd))
        return output(command) if callable(output) else output

    return GitHubIssue(repo, "dark", run), calls


def test_comments_carry_the_numeric_id_the_url_and_the_association(repo):
    payload = {"comments": [{"url": "https://github.com/o/r/issues/7#issuecomment-555", "body": "hi", "authorAssociation": "OWNER", "id": "IC_x"}]}
    issue, calls = issue_with(repo[0], json.dumps(payload))
    (comment,) = issue.comments()
    assert (comment.id, comment.body, comment.association) == (555, "hi", "OWNER") and comment.url.endswith("-555")
    assert calls[0][0] == ("gh", "issue", "view", "https://github.com/o/r/issues/7", "--json", "comments")


def test_a_run_with_no_issue_yet_has_no_comments(tmp_path):
    run = tmp_path / ".agent" / "runs" / "dark"
    run.mkdir(parents=True)
    RunState("idea").save(run / "state.json")
    issue, calls = issue_with(tmp_path, "")
    assert issue.comments() == [] and calls == []


def test_post_returns_the_new_comment_id(repo):
    issue, calls = issue_with(repo[0], "777")
    assert issue.post("/approve") == 777
    assert calls[0][0] == ("gh", "api", "-X", "POST", "repos/o/r/issues/7/comments", "-f", "body=/approve", "--jq", ".id")


def test_delete_targets_the_comment(repo):
    issue, calls = issue_with(repo[0], "")
    issue.delete(555)
    assert calls[0][0] == ("gh", "api", "-X", "DELETE", "repos/o/r/issues/comments/555")


def test_head_is_read_in_the_runs_worktree(repo):
    issue, calls = issue_with(repo[0], "abc123")
    assert issue.head() == "abc123" and calls[0] == (("git", "rev-parse", "HEAD"), repo[1])
