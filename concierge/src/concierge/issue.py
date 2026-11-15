import json
from collections.abc import Callable
from pathlib import Path

from concierge.requests import Comment
from pipeline.forge import RunState, run_command
from pipeline.run_dir import run_path


class GitHubIssue:
    """One run's issue, through `gh`, under the user's own login."""

    def __init__(self, repo: Path, slug: str, run: Callable[..., str] = run_command) -> None:
        self.repo = repo
        self.slug = slug
        self.run = run

    def comments(self) -> list[Comment]:
        if not (url := self._state().issue_url):
            return []
        output = self.run(("gh", "issue", "view", url, "--json", "comments"), self.repo, retry=True)
        return [Comment(int(c["url"].rsplit("-", 1)[1]), c["url"], c["body"], c["authorAssociation"]) for c in json.loads(output)["comments"]]

    def post(self, body: str) -> int:
        return int(self.run(("gh", "api", "-X", "POST", f"{self._issue_endpoint()}/comments", "-f", f"body={body}", "--jq", ".id"), self.repo))

    def delete(self, comment_id: int) -> None:
        owner_repo = "/".join(self._state().issue_url.split("/")[3:5])
        self.run(("gh", "api", "-X", "DELETE", f"repos/{owner_repo}/issues/comments/{comment_id}"), self.repo)

    def head(self) -> str:
        state = self._state()
        return self.run(("git", "rev-parse", "HEAD"), Path(state.worktree) if state.worktree else self.repo)

    def _state(self) -> RunState:
        return RunState.load(run_path(self.repo, self.slug) / "state.json")

    def _issue_endpoint(self) -> str:
        *_, owner, repo, _, number = self._state().issue_url.split("/")
        return f"repos/{owner}/{repo}/issues/{number}"
