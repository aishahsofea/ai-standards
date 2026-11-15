from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from concierge.actions import Action, invalid_reason, render_comment
from concierge.requests import Comment, allow_rules, decision_on, find_request, open_questions
from concierge.state import Bound, RunId, State
from pipeline.owner import ALLOW


class Gateway(Protocol):
    def comments(self) -> list[Comment]: ...
    def post(self, body: str) -> int: ...
    def delete(self, comment_id: int) -> None: ...
    def head(self) -> str: ...


@dataclass(frozen=True)
class Posted:
    comment_id: int
    body: str


@dataclass(frozen=True)
class Refused:
    reason: str


class Poster:
    def __init__(self, state: State, gateway_for: Callable[[RunId], Gateway]) -> None:
        self.state = state
        self.gateway_for = gateway_for

    def post(self, run: RunId, bound: Bound, action: Action, words: str = "") -> Posted | Refused:
        """Posts only if the issue still shows the request the user decided on, with no decision yet."""
        issue = self.gateway_for(run)
        if reason := self._refusal(issue, bound, action):
            return Refused(reason)
        body = render_comment(action, words)
        comment_id = issue.post(body)
        self.state.posted.append((str(run), comment_id))
        return Posted(comment_id, body)

    def undo(self, run: RunId) -> int | None:
        """Deletes the last comment posted for the run, the only way to reverse a decision."""
        mine = [entry for entry in self.state.posted if entry[0] == str(run)]
        if not mine:
            return None
        self.gateway_for(run).delete(mine[-1][1])
        self.state.posted.remove(mine[-1])
        return mine[-1][1]

    @staticmethod
    def _refusal(issue: Gateway, bound: Bound, action: Action) -> str | None:
        if reason := invalid_reason(bound.key, action):
            return reason
        comments = issue.comments()
        request = find_request(comments, bound.key)
        if request is None:
            return "the request was withdrawn"
        if (request.comment_id, request.digest) != (bound.comment_id, bound.digest):
            return "the request changed since you saw it"
        if bound.key == "gate-b" and issue.head() != bound.head:
            return "the branch moved since you saw it"
        if action.kind != "allow" and decision_on(comments, request):
            return "the request was already decided"
        match action.kind:
            case "revise" if not action.feedback.strip():
                return "there is no feedback to send"
            case "allow" if action.rule not in allow_rules(request):
                return "that rule is not one the request lists"
            case "allow" if action.rule in ALLOW.findall("\n".join(c.body for c in comments if c.trusted_reply)):
                return "that rule is already allowed"
            case "answer":
                open_numbers = open_questions(comments)
                if not action.answers:
                    return "there are no answers to send"
                return next((f"there is no open question Q{a.n}" for a in action.answers if a.n not in open_numbers), None)
        return None
