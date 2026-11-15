import hashlib
import re
from dataclasses import dataclass

from pipeline.forge import MARKER, TRUSTED, Decision, comment_text, first_command, request_name
from pipeline.gates import GateError, escalated_entries

HEAD = re.compile(r"Head commit: `([0-9a-f]+)`")
RULE = re.compile(r"(?m)^- `/allow (.+)`$")
QUESTION_NUMBER = re.compile(r"(?:(\d+)[.)]|\*\*Q(\d+))")
QUESTION_PREFIX = re.compile(r"^(?:\d+[.)]\s+|\*\*Q\d+[^*]*\*\*:?\s*)")


@dataclass(frozen=True)
class Comment:
    id: int
    url: str
    body: str
    association: str

    @property
    def artifact(self) -> str | None:
        match = MARKER.match(self.body)
        return match[1] if match else None

    @property
    def trusted_reply(self) -> bool:
        return self.artifact is None and self.association in TRUSTED


@dataclass(frozen=True)
class Request:
    key: str
    comment_id: int
    url: str
    text: str

    @property
    def head(self) -> str:
        match = HEAD.search(self.text)
        return match[1] if match else ""

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


def artifact_text(comments: list[Comment], name: str) -> str | None:
    comment = next((c for c in comments if c.artifact == name), None)
    return comment_text(name, comment.body) if comment else None


def find_request(comments: list[Comment], key: str) -> Request | None:
    name = request_name(key)
    comment = next((c for c in comments if c.artifact == name), None)
    return Request(key, comment.id, comment.url, comment_text(name, comment.body)) if comment else None


def decision_on(comments: list[Comment], request: Request) -> Decision | None:
    position = next(i for i, comment in enumerate(comments) if comment.id == request.comment_id)
    return first_command([c.body for c in comments[position + 1 :] if c.trusted_reply])


def allow_rules(request: Request) -> list[str]:
    return RULE.findall(request.text)


def open_questions(comments: list[Comment]) -> dict[int, str]:
    """The escalated questions without an answer, by the number a `Q<n>:` reply uses."""
    try:
        entries = escalated_entries(artifact_text(comments, "decisions") or "")
    except GateError:
        return {}
    numbered = ((QUESTION_NUMBER.match(entry), entry) for entry in entries)
    return {int(match[1] or match[2]): QUESTION_PREFIX.sub("", entry) for match, entry in numbered if match}
