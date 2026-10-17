import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from pipeline.run_dir import check_artifact

MAX_COMMENT_CHARS = 65_536
MARKER = re.compile(r"\A<!-- pipeline:artifact=(\S+) -->")
EXCLUDE_RUNS = ":!.agent/runs"


class ForgeError(Exception):
    pass


class Forge(Protocol):
    def start_branch(self) -> None: ...
    def open_issue(self, title: str, body: str) -> None: ...
    def checkpoint(self, message: str) -> None: ...
    def finish(self, pr_body: str) -> None: ...
    def post_artifact(self, name: str, text: str) -> None: ...
    def read_artifact(self, name: str) -> str | None: ...
    def has_artifact(self, name: str) -> bool: ...
    def human_comments_after(self, name: str) -> list[str]: ...


def heading(name: str) -> str:
    return "## " + re.sub(r"[-.]", " ", name).capitalize()


def comment_text(name: str, body: str) -> str:
    rest = MARKER.sub("", body, count=1).lstrip()
    return rest.removeprefix(heading(name)).lstrip()


def comment_body(name: str, text: str) -> str:
    check_artifact(name)
    body = f"<!-- pipeline:artifact={name} -->\n\n{heading(name)}\n\n{text}"
    if len(body) > MAX_COMMENT_CHARS:
        raise ForgeError(f"'{name}' comment is {len(body)} characters; GitHub allows {MAX_COMMENT_CHARS}")
    return body


@dataclass(frozen=True)
class Issue:
    title: str
    body: str
    url: str

    @property
    def number(self) -> str:
        return self.url.rsplit("/", 1)[-1]

    @property
    def markdown(self) -> str:
        return f"# {self.title}\n\n{self.body}\n"


def fetch_issue(repo: Path, ref: str) -> Issue:
    proc = subprocess.run(
        ["gh", "issue", "view", ref, "--json", "title,body,url"], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise ForgeError(f"gh issue view failed: {proc.stderr.strip()}")
    return Issue(**json.loads(proc.stdout))


@dataclass
class RunState:
    idea: str
    issue_url: str = ""
    pr_url: str = ""

    @classmethod
    def load(cls, path: Path) -> "RunState":
        return cls(**json.loads(path.read_text()))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")


class FakeForge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.artifacts: dict[str, str] = {}
        self.posts: list[str] = []
        self.replies: list[str] = []

    def start_branch(self) -> None:
        self.calls.append(("start_branch",))

    def open_issue(self, title: str, body: str) -> None:
        self.calls.append(("open_issue", title))
        self.artifacts["issue"] = body

    def checkpoint(self, message: str) -> None:
        self.calls.append(("checkpoint", message))

    def finish(self, pr_body: str) -> None:
        self.calls.append(("finish", pr_body))

    def post_artifact(self, name: str, text: str) -> None:
        comment_body(name, text)
        self.artifacts[name] = text
        self.posts.append(name)

    def read_artifact(self, name: str) -> str | None:
        return self.artifacts.get(name)

    def has_artifact(self, name: str) -> bool:
        return name in self.artifacts

    def human_comments_after(self, name: str) -> list[str]:
        return list(self.replies)


class GitHubForge:
    def __init__(self, repo: Path, slug: str, state: RunState, state_path: Path) -> None:
        self.repo = repo
        self.slug = slug
        self.branch = f"agent/{slug}"
        self.state = state
        self.state_path = state_path
        self._view: dict | None = None

    def start_branch(self) -> None:
        if self._run("git", "branch", "--list", self.branch):
            self._run("git", "checkout", self.branch)
        elif self._run("git", "status", "--porcelain", "--", ".", EXCLUDE_RUNS):
            raise ForgeError("working tree has uncommitted changes; commit or stash them first")
        else:
            self._run("git", "checkout", "-b", self.branch)

    def open_issue(self, title: str, body: str) -> None:
        if self.state.issue_url:
            return
        output = self._run("gh", "issue", "create", "--title", title, "--body", body)
        self.state.issue_url = output.splitlines()[-1]
        self.state.save(self.state_path)
        self._view = None

    def checkpoint(self, message: str) -> None:
        self._run("git", "add", "-A", "--", ".", EXCLUDE_RUNS)
        if self._run("git", "diff", "--cached", "--name-only"):
            self._run("git", "commit", "-m", message)
        self._run("git", "push", "-u", "origin", self.branch)
        if not self.state.pr_url and self._has_commits_to_review():
            self._open_draft_pr()

    def finish(self, pr_body: str) -> None:
        if not self.state.pr_url:
            self._open_draft_pr()
        self._run("gh", "pr", "edit", self.state.pr_url, "--body", f"{pr_body}\n\nCloses {self.state.issue_url}")
        self._run("gh", "pr", "ready", self.state.pr_url)

    def post_artifact(self, name: str, text: str) -> None:
        body = comment_body(name, text)
        if not self.state.issue_url:
            raise ForgeError(f"no issue yet to post the '{name}' comment on")
        existing = self._artifact_comments().get(name)
        if existing:
            comment_id = existing["url"].rsplit("-", 1)[1]
            repo = "/".join(self.state.issue_url.split("/")[3:5])
            self._run("gh", "api", "-X", "PATCH", f"repos/{repo}/issues/comments/{comment_id}", "-f", f"body={body}")
        else:
            self._run("gh", "issue", "comment", self.state.issue_url, "--body", body)
        self._view = None

    def read_artifact(self, name: str) -> str | None:
        if not self.state.issue_url:
            return None
        if name == "issue":
            view = self._issue_view()
            return Issue(view["title"], view["body"], view["url"]).markdown
        comment = self._artifact_comments().get(name)
        return comment_text(name, comment["body"]) if comment else None

    def has_artifact(self, name: str) -> bool:
        if not self.state.issue_url:
            return False
        return name == "issue" or name in self._artifact_comments()

    def human_comments_after(self, name: str) -> list[str]:
        comments = self._issue_view()["comments"] if self.state.issue_url else []
        position = next((i for i, c in enumerate(comments) if self._artifact_name(c) == name), None)
        if position is None:
            return []
        return [c["body"] for c in comments[position + 1 :] if not self._artifact_name(c)]

    def _issue_view(self) -> dict:
        if self._view is None:
            output = self._run("gh", "issue", "view", self.state.issue_url, "--json", "title,body,url,comments")
            self._view = json.loads(output)
        return self._view

    def _artifact_comments(self) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for comment in self._issue_view()["comments"]:
            if name := self._artifact_name(comment):
                found.setdefault(name, comment)
        return found

    @staticmethod
    def _artifact_name(comment: dict) -> str | None:
        match = MARKER.match(comment["body"])
        return match[1] if match else None

    def _has_commits_to_review(self) -> bool:
        base = self._run("gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name")
        return int(self._run("git", "rev-list", "--count", f"origin/{base}..HEAD") or 0) > 0

    def _open_draft_pr(self) -> None:
        body = f"Draft opened by the agent pipeline. Closes {self.state.issue_url}"
        output = self._run("gh", "pr", "create", "--draft", "--title", self.state.idea[:70], "--body", body)
        self.state.pr_url = output.splitlines()[-1]
        self.state.save(self.state_path)

    def _run(self, *command: str) -> str:
        proc = subprocess.run(command, cwd=self.repo, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ForgeError(f"{' '.join(command[:3])} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()
