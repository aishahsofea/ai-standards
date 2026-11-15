import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import NamedTuple


class RunId(NamedTuple):
    repo: str
    slug: str

    def __str__(self) -> str:
        return f"{self.repo}/{self.slug}"

    @classmethod
    def parse(cls, text: str) -> "RunId":
        return cls(*text.rsplit("/", 1))


@dataclass
class Bound:
    """The request a decision was made against."""

    key: str
    comment_id: int
    digest: str
    head: str = ""


@dataclass
class Message:
    run: str
    bound: Bound
    kind: str
    action: dict | None = None
    words: str = ""
    rules: list[str] = field(default_factory=list)


@dataclass
class RunRecord:
    status: str = "queued"
    request: str = ""
    spent_usd: float = 0.0
    events_offset: int = 0
    note: str = ""


@dataclass
class State:
    """A cache: losing it loses only reply threading and the daily spend."""

    path: Path
    runs: dict[str, RunRecord] = field(default_factory=dict)
    messages: dict[str, Message] = field(default_factory=dict)
    spend: dict[str, float] = field(default_factory=dict)
    notified: dict[str, str] = field(default_factory=dict)
    posted: list[tuple[str, int]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls(path)
        data = json.loads(path.read_text())
        return cls(
            path,
            {run: RunRecord(**record) for run, record in data["runs"].items()},
            {mid: Message(m["run"], Bound(**m["bound"]), m["kind"], m["action"], m["words"], m["rules"]) for mid, m in data["messages"].items()},
            data["spend"],
            data["notified"],
            [(run, comment_id) for run, comment_id in data["posted"]],
        )

    def save(self) -> None:
        data = {key: value for key, value in asdict(self).items() if key != "path"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(temp, self.path)

    def drop_messages(self, run: str) -> None:
        self.messages = {mid: message for mid, message in self.messages.items() if message.run != run}
