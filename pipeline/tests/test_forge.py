import json
import subprocess
from pathlib import Path

import pytest

from pipeline.forge import Check, Decision, FakeForge, ForgeError, GitHubForge, Issue, RunState, fetch_issue


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
    assert shell.ran("git", "ls-files", "-z", "--others", "--exclude-standard", "--", ".", ":!.agent/runs")
    assert shell.ran("git", "diff", "-z", "--name-only", "HEAD", "--", ".", ":!.agent/runs")


def test_checkpoint_stages_only_paths_changed_since_start(make):
    listings = iter(["stray.md", "stray.md\0src/new.py"])
    forge, shell, _ = make(git_ls=lambda: next(listings))
    forge.start_branch()
    forge.checkpoint("test")
    assert shell.ran("git", "add", "-A", "--", ":(literal)src/new.py")
    assert not [c for c in shell.ran("git", "add") if any("stray.md" in arg for arg in c)]


def test_checkpoint_stages_nothing_when_only_preexisting_paths_are_dirty(make):
    forge, shell, _ = make(git_ls="stray.md")
    forge.start_branch()
    forge.checkpoint("test")
    assert not shell.ran("git", "add")


def test_resume_keeps_the_baseline_from_the_first_start(make):
    listings = iter(["stray.md", "stray.md\0src/new.py"])
    forge, shell, state = make(git_ls=lambda: next(listings))
    forge.start_branch()
    assert state.baseline == ["stray.md"]
    forge.start_branch()
    forge.checkpoint("phase 1")
    assert shell.ran("git", "add", "-A", "--", ":(literal)src/new.py")


def test_run_state_without_baseline_loads_from_older_files(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"idea": "x", "issue_url": "", "pr_url": ""}')
    assert RunState.load(path).baseline is None


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
    assert shell.ran("git", "push", "-u", "origin", "agent/add-dark-mode")
    edit = shell.ran("gh", "pr", "edit")[0]
    assert edit[-1] == "PR text\n\nCloses https://github.com/o/r/issues/7"
    assert shell.ran("gh", "pr", "ready", "https://github.com/o/r/pull/9")


def test_finish_pushes_before_opening_a_missing_pr(make):
    forge, shell, state = make(gh_pr="https://github.com/o/r/pull/9")
    state.issue_url = "https://github.com/o/r/issues/7"
    forge.finish("PR text")
    commands = [c[:2] for c in shell.commands]
    assert commands.index(("git", "push")) < commands.index(("gh", "pr"))
    assert state.pr_url == "https://github.com/o/r/pull/9"


def test_command_failure_raises(make):
    forge, _, _ = make(git_ls="a.py", git_add=None)
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


def comment(name, text="body", id=101, association="OWNER"):
    body = f"<!-- pipeline:artifact={name} -->\n\n## {name.title()}\n\n{text}" if name else text
    return {"url": f"{ISSUE_URL}#issuecomment-{id}", "body": body, "authorAssociation": association}


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


def test_human_comments_from_non_collaborators_are_ignored(issue_forge):
    forge, _, comments = issue_forge
    comments += [
        comment("decisions", id=1), comment(None, "drive-by", 2, "NONE"), comment(None, "past contributor", 3, "CONTRIBUTOR"),
        comment(None, "member", 4, "MEMBER"), comment(None, "collaborator", 5, "COLLABORATOR"),
    ]
    assert forge.human_comments_after("decisions") == ["member", "collaborator"]


def test_request_posts_a_request_comment(issue_forge):
    forge, shell, _ = issue_forge
    forge.request("plan", "plan done. Continue?")
    (posted,) = shell.ran("gh", "issue", "comment")
    assert posted[-1].startswith("<!-- pipeline:artifact=request-plan -->") and "plan done. Continue?" in posted[-1]


def test_decision_is_the_first_command_reply_after_the_request(issue_forge):
    forge, _, comments = issue_forge
    comments += [
        comment(None, "/approve", 1), comment("request-plan", id=2), comment(None, "looks fine to me", 3),
        comment(None, "/reject", 4), comment(None, "/approve", 5),
    ]
    assert forge.decision("plan") == Decision("reject")


def test_decision_keeps_the_text_after_the_command(issue_forge):
    forge, _, comments = issue_forge
    comments += [comment("request-gate-b", id=1), comment(None, "/revise Use a modal\n\nnot inline", 2)]
    assert forge.decision("gate-b") == Decision("revise", "Use a modal\n\nnot inline")


def test_decision_ignores_non_collaborators(issue_forge):
    forge, _, comments = issue_forge
    comments += [comment("request-plan", id=1), comment(None, "/approve", 2, "NONE")]
    assert forge.decision("plan") is None


def test_no_decision_without_a_request_or_a_command(issue_forge):
    forge, _, comments = issue_forge
    comments += [comment(None, "/approve", 1)]
    assert forge.decision("plan") is None
    comments += [comment("request-plan", id=2), comment(None, "/approved by me", 3), comment(None, "see /approve", 4)]
    assert forge.decision("plan") is None


def test_owner_replies_are_every_trusted_human_comment(issue_forge):
    forge, _, comments = issue_forge
    comments += [comment(None, "/allow Bash(make:*)", 1), comment("plan", id=2), comment(None, "/allow Bash(rm:*)", 3, "NONE")]
    assert forge.owner_replies() == ["/allow Bash(make:*)"]
    assert FakeForge().owner_replies() == []


def test_withdraw_deletes_the_request_comment(issue_forge):
    forge, shell, comments = issue_forge
    comments.append(comment("request-gate-b", id=77))
    forge.withdraw("gate-b")
    assert shell.ran("gh", "api", "-X", "DELETE") == [("gh", "api", "-X", "DELETE", "repos/o/r/issues/comments/77")]
    forge.withdraw("plan")
    assert len(shell.ran("gh", "api", "-X", "DELETE")) == 1


def test_head_is_the_local_commit(make):
    forge, _, _ = make(**{"git_rev-parse": "abc123"})
    assert forge.head() == "abc123"


def test_fake_forge_withdrawn_request_forgets_its_replies():
    forge = FakeForge()
    forge.request("gate-b", "Ready?")
    forge.reply("/approve")
    forge.withdraw("gate-b")
    assert not forge.has_artifact("request-gate-b")
    forge.request("gate-b", "Ready?")
    assert forge.decision("gate-b") is None


def test_fake_forge_decides_from_trusted_replies_after_the_request():
    forge = FakeForge()
    forge.reply("/reject")
    forge.request("plan", "Continue?")
    assert forge.read_artifact("request-plan") == "Continue?" and forge.decision("plan") is None
    forge.reply("/approve", "NONE")
    assert forge.decision("plan") is None and forge.human_comments_after("plan") == ["/reject"]
    forge.reply("/allow Bash(docker ps:*)")
    forge.reply("/approve")
    assert forge.decision("plan") == Decision("allow", "Bash(docker ps:*)")


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


PR_URL = "https://github.com/o/r/pull/9"
RUN_LINK = "https://github.com/o/r/actions/runs/5/job/1"


def rollup(*entries):
    return json.dumps({"headRefOid": "abc", "statusCheckRollup": list(entries)})


def run_entry(name, status="COMPLETED", conclusion="SUCCESS", link=RUN_LINK):
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion, "detailsUrl": link}


def test_ci_checks_map_check_runs_and_commit_statuses(make):
    status = {"__typename": "StatusContext", "context": "vercel", "state": "ERROR", "targetUrl": "https://v"}
    forge, _, state = make(
        gh_pr_view=rollup(
            run_entry("unit"), run_entry("lint", conclusion="FAILURE"), run_entry("e2e", "IN_PROGRESS", ""),
            run_entry("docs", conclusion="SKIPPED"), status,
        ),
        **{"git_rev-parse": "abc"},
    )
    state.pr_url = PR_URL
    assert [(c.name, c.state) for c in forge.ci_checks()] == [
        ("unit", "pass"), ("lint", "fail"), ("e2e", "pending"), ("docs", "pass"), ("vercel", "fail"),
    ]


def test_ci_checks_wait_until_github_reports_the_local_head(make):
    forge, _, state = make(gh_pr_view=rollup(run_entry("unit")), **{"git_rev-parse": "def"})
    state.pr_url = PR_URL
    assert forge.ci_checks() is None


def test_ci_checks_without_a_pr_are_empty(make):
    forge, shell, _ = make()
    assert forge.ci_checks() == []
    assert not shell.commands


def test_ci_logs_fetch_each_run_once_and_keep_only_the_tail(make):
    forge, shell, _ = make(gh_run_view="start-of-log" + "x" * 20_000 + "the-error")
    failing = [Check("lint", "fail", RUN_LINK), Check("types", "fail", RUN_LINK), Check("vercel", "fail", "https://v")]
    logs = forge.ci_logs(failing)
    assert len(shell.ran("gh", "run", "view", "5", "--log-failed")) == 1
    assert "the-error" in logs and "start-of-log" not in logs
    assert "- vercel https://v" in logs


def test_ci_logs_survive_an_unreadable_run(make):
    forge, _, _ = make(gh_run_view=None)
    assert "(log unavailable" in forge.ci_logs([Check("lint", "fail", RUN_LINK)])


def test_base_failures_query_the_default_branch_check_runs(make):
    forge, shell, _ = make(gh_repo="main", gh_api="lint\nunit")
    assert forge.base_failures() == {"lint", "unit"}
    assert shell.ran("gh", "api", "repos/{owner}/{repo}/commits/main/check-runs")


def test_rerun_checks_reruns_each_failed_run_once(make):
    forge, shell, _ = make()
    forge.rerun_checks([Check("lint", "fail", RUN_LINK), Check("types", "fail", RUN_LINK), Check("vercel", "fail")])
    assert shell.ran("gh", "run", "rerun", "5", "--failed") and len(shell.ran("gh", "run", "rerun")) == 1
