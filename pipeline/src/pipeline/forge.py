import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


class ForgeError(Exception):
    pass


class Forge(Protocol):
    def start_branch(self) -> None: ...
    def open_issue(self, title: str, body: str) -> None: ...
    def checkpoint(self, message: str) -> None: ...
    def finish(self, pr_body: str) -> None: ...


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

    def start_branch(self) -> None:
        self.calls.append(("start_branch",))

    def open_issue(self, title: str, body: str) -> None:
        self.calls.append(("open_issue", title))

    def checkpoint(self, message: str) -> None:
        self.calls.append(("checkpoint", message))

    def finish(self, pr_body: str) -> None:
        self.calls.append(("finish", pr_body))


class GitHubForge:
    def __init__(self, repo: Path, slug: str, state: RunState, state_path: Path) -> None:
        self.repo = repo
        self.slug = slug
        self.branch = f"agent/{slug}"
        self.state = state
        self.state_path = state_path

    def start_branch(self) -> None:
        if self._run("git", "branch", "--list", self.branch):
            self._run("git", "checkout", self.branch)
        elif self._run("git", "status", "--porcelain"):
            raise ForgeError("working tree has uncommitted changes; commit or stash them first")
        else:
            self._run("git", "checkout", "-b", self.branch)

    def open_issue(self, title: str, body: str) -> None:
        if self.state.issue_url:
            return
        output = self._run("gh", "issue", "create", "--title", title, "--body", body)
        self.state.issue_url = output.splitlines()[-1]
        self.state.save(self.state_path)

    def checkpoint(self, message: str) -> None:
        self._run("git", "add", "-A")
        if self._run("git", "status", "--porcelain"):
            self._run("git", "commit", "-m", f"pipeline: {message}")
        self._run("git", "push", "-u", "origin", self.branch)
        if not self.state.pr_url:
            self._open_draft_pr()

    def finish(self, pr_body: str) -> None:
        self._run("gh", "pr", "edit", self.state.pr_url, "--body", f"{pr_body}\n\nCloses {self.state.issue_url}")
        self._run("gh", "pr", "ready", self.state.pr_url)

    def _open_draft_pr(self) -> None:
        body = f"Draft opened by the agent pipeline. Closes {self.state.issue_url}"
        output = self._run("gh", "pr", "create", "--draft", "--title", self.state.idea[:70], "--body", body)
        self.state.pr_url = output.splitlines()[-1]
        self.state.save(self.state_path)
        self._run(
            "gh", "issue", "comment", self.state.issue_url,
            "--body", f"Run artifacts: `.agent/runs/{self.slug}/` on {self.state.pr_url}",
        )

    def _run(self, *command: str) -> str:
        proc = subprocess.run(command, cwd=self.repo, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ForgeError(f"{' '.join(command[:3])} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()
