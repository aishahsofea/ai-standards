import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from pipeline.run_dir import check_artifact

MAX_COMMENT_CHARS = 65_536
MARKER = re.compile(r"\A<!-- pipeline:artifact=(\S+) -->")
EXCLUDE_RUNS = ":!.agent/runs"
RETRY_DELAYS = (1, 2)
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
QUOTED = re.compile(r"(?m)^>.*\n?")
COMMAND = re.compile(r"/(approve|reject|revise|allow)(?!\S)\s*(.*)", re.DOTALL)


class ForgeError(Exception):
    pass


def run_command(command: tuple[str, ...], cwd: Path, *, retry: bool = False) -> str:
    for delay in (*RETRY_DELAYS, None) if retry else (None,):
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if proc.returncode == 0:
            return proc.stdout.strip()
        if delay is None:
            raise ForgeError(f"{' '.join(command[:3])} failed: {proc.stderr.strip()}")
        time.sleep(delay)


def branch_name(slug: str) -> str:
    return f"agent/{slug}"


CheckState = Literal["pass", "fail", "pending"]
RUN_ID = re.compile(r"/actions/runs/(\d+)")
PASSING = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILING = {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED", "CANCELLED", "STALE", "ERROR"}
LOG_TAIL_CHARS = 10_000
MAX_LOG_RUNS = 4


@dataclass(frozen=True)
class Check:
    name: str
    state: CheckState
    link: str = ""

    @property
    def run_id(self) -> str | None:
        match = RUN_ID.search(self.link)
        return match[1] if match else None


def check_from_rollup(entry: dict) -> Check:
    """Reads a `statusCheckRollup` entry, either a check run or a commit status."""
    if entry["__typename"] == "StatusContext":
        name, result, link = entry["context"], entry["state"], entry.get("targetUrl", "")
    else:
        name, link = entry["name"], entry.get("detailsUrl", "")
        result = entry["conclusion"] if entry["status"] == "COMPLETED" else "PENDING"
    state = "pass" if result in PASSING else "fail" if result in FAILING else "pending"
    return Check(name, state, link)


@dataclass(frozen=True)
class Decision:
    command: str
    text: str = ""


def request_name(key: str) -> str:
    return f"request-{key}"


def first_command(replies: list[str]) -> Decision | None:
    matches = (COMMAND.match(QUOTED.sub("", reply).strip()) for reply in replies)
    return next((Decision(match[1], match[2].strip()) for match in matches if match), None)


class Forge(Protocol):
    def start_branch(self) -> None: ...
    def open_issue(self, title: str, body: str) -> None: ...
    def checkpoint(self, message: str) -> None: ...
    def finish(self, pr_body: str) -> None: ...
    def post_artifact(self, name: str, text: str) -> None: ...
    def read_artifact(self, name: str) -> str | None: ...
    def has_artifact(self, name: str) -> bool: ...
    def human_comments_after(self, name: str) -> list[str]: ...
    def owner_replies(self) -> list[str]: ...
    def request(self, key: str, text: str) -> None: ...
    def decision(self, key: str) -> Decision | None: ...
    def withdraw(self, key: str) -> None: ...
    def head(self) -> str: ...
    def ci_checks(self) -> list[Check] | None: ...
    def ci_logs(self, failing: list[Check]) -> str: ...
    def base_failures(self) -> set[str]: ...
    def rerun_checks(self, failing: list[Check]) -> None: ...


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
    output = run_command(("gh", "issue", "view", ref, "--json", "title,body,url"), repo, retry=True)
    return Issue(**json.loads(output))


def pipeline_issues(repo: Path) -> list[dict]:
    """Every issue in the repo with a stage comment, with its comments, oldest first."""
    command = ("gh", "issue", "list", "--state", "all", "--search", "pipeline:artifact in:comments", "--limit", "500", "--json", "number,title,comments")
    return sorted(json.loads(run_command(command, repo, retry=True)), key=lambda issue: issue["number"])


@dataclass
class RunState:
    idea: str
    issue_url: str = ""
    pr_url: str = ""
    baseline: list[str] | None = None
    worktree: str = ""

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
        self.requested_at: dict[str, int] = {}
        self.head_commit = "c0ffee"
        self.ci_results: list[list[Check] | None] = [[Check("ci", "pass")]]
        self.on_base: set[str] = set()

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

    def owner_replies(self) -> list[str]:
        return list(self.replies)

    def reply(self, body: str, association: str = "OWNER") -> None:
        if association in TRUSTED:
            self.replies.append(body)

    def request(self, key: str, text: str) -> None:
        self.post_artifact(request_name(key), text)
        self.requested_at.setdefault(key, len(self.replies))

    def decision(self, key: str) -> Decision | None:
        return first_command(self.replies[self.requested_at[key] :]) if key in self.requested_at else None

    def withdraw(self, key: str) -> None:
        self.calls.append(("withdraw", key))
        del self.artifacts[request_name(key)], self.requested_at[key]

    def head(self) -> str:
        return self.head_commit

    def ci_checks(self) -> list[Check] | None:
        return self.ci_results.pop(0) if len(self.ci_results) > 1 else self.ci_results[0]

    def ci_logs(self, failing: list[Check]) -> str:
        self.calls.append(("ci_logs", *(check.name for check in failing)))
        return "log of " + ", ".join(check.name for check in failing)

    def base_failures(self) -> set[str]:
        return self.on_base

    def rerun_checks(self, failing: list[Check]) -> None:
        self.calls.append(("rerun", *(check.name for check in failing)))


class GitHubForge:
    def __init__(self, repo: Path, slug: str, state: RunState, state_path: Path) -> None:
        self.repo = repo
        self.slug = slug
        self.branch = branch_name(slug)
        self.state = state
        self.state_path = state_path
        self._view: dict | None = None
        self._preexisting: set[str] = set()

    def start_branch(self) -> None:
        if self._run("git", "branch", "--list", self.branch):
            self._run("git", "checkout", self.branch)
        elif self._run("git", "status", "--porcelain", "--", ".", EXCLUDE_RUNS):
            raise ForgeError("working tree has uncommitted changes; commit or stash them first")
        else:
            self._run("git", "checkout", "-b", self.branch)
        if self.state.baseline is None:
            self.state.baseline = sorted(self._changed_paths())
        self._preexisting = set(self.state.baseline)

    def open_issue(self, title: str, body: str) -> None:
        if self.state.issue_url:
            return
        output = self._run("gh", "issue", "create", "--title", title, "--body", body)
        self.state.issue_url = output.splitlines()[-1]
        self.state.save(self.state_path)
        self._view = None

    def checkpoint(self, message: str) -> None:
        if paths := sorted(self._changed_paths() - self._preexisting):
            self._run("git", "add", "-A", "--", *(f":(literal){path}" for path in paths))
        if self._run("git", "diff", "--cached", "--name-only"):
            self._run("git", "commit", "-m", message)
        self._run("git", "push", "-u", "origin", self.branch)
        if not self.state.pr_url and self._has_commits_to_review():
            self._open_draft_pr()

    def finish(self, pr_body: str) -> None:
        self._run("git", "push", "-u", "origin", self.branch)
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
            self._run("gh", "api", "-X", "PATCH", self._comment_endpoint(existing), "-f", f"body={body}")
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
        return self._trusted_replies(comments[position + 1 :])

    def owner_replies(self) -> list[str]:
        return self._trusted_replies(self._issue_view()["comments"]) if self.state.issue_url else []

    def request(self, key: str, text: str) -> None:
        self.post_artifact(request_name(key), text)

    def decision(self, key: str) -> Decision | None:
        return first_command(self.human_comments_after(request_name(key)))

    def withdraw(self, key: str) -> None:
        if comment := self._artifact_comments().get(request_name(key)):
            self._run("gh", "api", "-X", "DELETE", self._comment_endpoint(comment))
            self._view = None

    def head(self) -> str:
        return self._run("git", "rev-parse", "HEAD")

    def ci_checks(self) -> list[Check] | None:
        """None until GitHub reports the local HEAD as the PR head."""
        if not self.state.pr_url:
            return []
        output = self._run("gh", "pr", "view", self.state.pr_url, "--json", "headRefOid,statusCheckRollup", retry=True)
        view = json.loads(output)
        if view["headRefOid"] != self.head():
            return None
        return [check_from_rollup(entry) for entry in view["statusCheckRollup"]]

    def ci_logs(self, failing: list[Check]) -> str:
        sections = ["Failing checks:", *(f"- {check.name} {check.link}".rstrip() for check in failing)]
        for run_id in list(dict.fromkeys(check.run_id for check in failing if check.run_id))[:MAX_LOG_RUNS]:
            try:
                log = self._run("gh", "run", "view", run_id, "--log-failed", retry=True)[-LOG_TAIL_CHARS:]
            except ForgeError as error:
                log = f"(log unavailable: {error})"
            sections.append(f"## Run {run_id} (end of the failed-step log)\n\n{log}")
        return "\n\n".join(sections)

    def base_failures(self) -> set[str]:
        query = '.check_runs[] | select(.conclusion == "failure") | .name'
        endpoint = f"repos/{{owner}}/{{repo}}/commits/{self._default_branch()}/check-runs"
        return set(self._run("gh", "api", endpoint, "--jq", query, retry=True).splitlines())

    def rerun_checks(self, failing: list[Check]) -> None:
        for run_id in dict.fromkeys(check.run_id for check in failing if check.run_id):
            self._run("gh", "run", "rerun", run_id, "--failed")

    def _default_branch(self) -> str:
        return self._run("gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name", retry=True)

    def _changed_paths(self) -> set[str]:
        untracked = self._run("git", "ls-files", "-z", "--others", "--exclude-standard", "--", ".", EXCLUDE_RUNS)
        modified = self._run("git", "diff", "-z", "--name-only", "HEAD", "--", ".", EXCLUDE_RUNS)
        return {path for path in f"{untracked}\0{modified}".split("\0") if path}

    def _issue_view(self) -> dict:
        if self._view is None:
            output = self._run(
                "gh", "issue", "view", self.state.issue_url, "--json", "title,body,url,comments", retry=True
            )
            self._view = json.loads(output)
        return self._view

    def _artifact_comments(self) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for comment in self._issue_view()["comments"]:
            if name := self._artifact_name(comment):
                found.setdefault(name, comment)
        return found

    def _trusted_replies(self, comments: list[dict]) -> list[str]:
        return [c["body"] for c in comments if not self._artifact_name(c) and c["authorAssociation"] in TRUSTED]

    def _comment_endpoint(self, comment: dict) -> str:
        repo = "/".join(self.state.issue_url.split("/")[3:5])
        return f"repos/{repo}/issues/comments/{comment['url'].rsplit('-', 1)[1]}"

    @staticmethod
    def _artifact_name(comment: dict) -> str | None:
        match = MARKER.match(comment["body"])
        return match[1] if match else None

    def _has_commits_to_review(self) -> bool:
        return int(self._run("git", "rev-list", "--count", f"origin/{self._default_branch()}..HEAD") or 0) > 0

    def _open_draft_pr(self) -> None:
        body = f"Draft opened by the agent pipeline. Closes {self.state.issue_url}"
        output = self._run("gh", "pr", "create", "--draft", "--title", self.state.idea[:70], "--body", body)
        self.state.pr_url = output.splitlines()[-1]
        self.state.save(self.state_path)

    def _run(self, *command: str, retry: bool = False) -> str:
        return run_command(command, self.repo, retry=retry)
