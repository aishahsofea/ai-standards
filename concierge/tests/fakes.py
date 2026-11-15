import json
from pathlib import Path

from concierge.requests import Comment
from pipeline.forge import comment_body, request_name


class FakeIssue:
    """An issue's comments, shaped like GitHub's, for one run."""

    def __init__(self) -> None:
        self.items: list[Comment] = []
        self.head_commit = "c0ffee"
        self.next_id = 100
        self.posted: list[int] = []
        self.deleted: list[int] = []

    def comments(self) -> list[Comment]:
        return list(self.items)

    def add(self, body: str, association: str = "OWNER") -> int:
        self.next_id += 1
        self.items.append(Comment(self.next_id, f"https://github.com/o/r/issues/1#issuecomment-{self.next_id}", body, association))
        return self.next_id

    def artifact(self, name: str, text: str) -> int:
        return self.add(comment_body(name, text), "OWNER")

    def request(self, key: str, text: str) -> int:
        return self.artifact(request_name(key), text)

    def reply(self, body: str, association: str = "OWNER") -> int:
        return self.add(body, association)

    def post(self, body: str) -> int:
        comment_id = self.add(body)
        self.posted.append(comment_id)
        return comment_id

    def delete(self, comment_id: int) -> None:
        self.deleted.append(comment_id)
        self.items = [comment for comment in self.items if comment.id != comment_id]

    def replace_text(self, comment_id: int, key: str, text: str) -> None:
        """Edits a request in place, as the pipeline does when a request's text changes."""
        self.items = [
            Comment(c.id, c.url, comment_body(request_name(key), text), c.association) if c.id == comment_id else c for c in self.items
        ]

    def head(self) -> str:
        return self.head_commit


class FakeProcess:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.code: int | None = None
        self.output = ""
        self.interrupted = False

    def poll(self) -> int | None:
        return self.code

    def tail(self) -> str:
        return self.output

    def interrupt(self) -> None:
        self.interrupted = True

    def exit(self, code: int, **result) -> None:
        self.code = code
        if result:
            self.output = "Working...\n" + json.dumps({"stage": None, "request": None, "spent_usd": 0.0, **result}) + "\n"


class FakeSpawn:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []
        self.cwds: list[Path] = []

    def __call__(self, argv: list[str], cwd: Path, log: Path) -> FakeProcess:
        self.processes.append(FakeProcess(argv))
        self.cwds.append(cwd)
        return self.processes[-1]


class FakeCaffeinate:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def __call__(self):
        self.started += 1
        return self

    def terminate(self) -> None:
        self.stopped += 1
