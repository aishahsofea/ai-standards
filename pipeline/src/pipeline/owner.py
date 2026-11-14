import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pipeline.agent import Denial
from pipeline.forge import Forge, request_name
from pipeline.gates import GATE_A, GATE_B, escalated_entries

CONVENTION = "convention"
STEP = "step"
ALLOW_KEY = "allow"
RERUN = "then run the same command again."
REPLY_HELP = f"Reply `/approve` to continue or `/reject` to stop, {RERUN}"
GATE_A_HELP = (
    "The decisions comment has escalated questions without an answer. Reply `Q<n>: <answer>` for each one; start the "
    f"answer with `!` if it changes an earlier decision. Reply `/approve` to accept every recommendation instead, {RERUN}"
)
GATE_B_HELP = f"Reply `/approve` to mark the PR ready, `/revise <feedback>` to change it, or `/reject` to stop, {RERUN}"
QUESTION = re.compile(r"\bQ(\d+)\b")
ANSWER = re.compile(r"(?m)^Q(\d+):[ \t]*(.+)$")
ALLOW = re.compile(r"(?m)^/allow[ \t]+`?([^`\n]+?)`?[ \t]*$")
ALLOW_HELP = f"The agent was denied these commands. Reply `/allow <rule>` for each one it may run, {RERUN}"


class Owner(Protocol):
    """The person who decides at each ask point; `key` names the ask point."""

    asks_on_resume: bool
    waiting: str | None

    def confirm(self, key: str, question: str, details: str = "") -> bool: ...
    def reader(self, key: str) -> Callable[[str], str] | None: ...
    def approve(self, denials: tuple[Denial, ...]) -> bool: ...
    def notify(self, message: str) -> None: ...


@dataclass
class TerminalOwner:
    ask_yes_no: Callable[[str], bool]
    read_line: Callable[[str], str] | None = None
    allow: Callable[[tuple[Denial, ...]], bool] | None = None
    alert: Callable[[str], None] = lambda _: None
    asks_on_resume = False
    waiting = None

    def confirm(self, key: str, question: str, details: str = "") -> bool:
        return self.ask_yes_no(question)

    def reader(self, key: str) -> Callable[[str], str] | None:
        return self.read_line

    def approve(self, denials: tuple[Denial, ...]) -> bool:
        return bool(self.allow and self.allow(denials))

    def notify(self, message: str) -> None:
        self.alert(message)


@dataclass
class HeadlessOwner:
    """Reads the owner's decisions from replies on the issue; `waiting` is the request still without one."""

    forge: Forge
    allowed: list[str] = field(default_factory=list)
    waiting: str | None = None
    asks_on_resume = True

    def __post_init__(self) -> None:
        self.allowed.extend(self._allowed_on_issue())

    def confirm(self, key: str, question: str, details: str = "") -> bool:
        if key == CONVENTION:
            return False
        if key == GATE_A.key:
            return self._answered()
        if key == GATE_B.key:
            return self._decided(key, f"{question}\n\n{self._head_binding()}\n\n{GATE_B_HELP}")
        return self._decided(key, "\n\n".join(part for part in (question, details, REPLY_HELP) if part))

    def reader(self, key: str) -> Callable[[str], str] | None:
        return {GATE_A.key: self._answer, GATE_B.key: self._take_feedback}.get(key)

    def approve(self, denials: tuple[Denial, ...]) -> bool:
        """True when the owner allowed a denied rule since the run started; otherwise asks for the rules and waits."""
        denied = sorted({denial.rule for denial in denials})
        if granted := [rule for rule in self._allowed_on_issue() if rule in denied and rule not in self.allowed]:
            self.allowed.extend(granted)
            return True
        text = "\n".join([ALLOW_HELP, "", *(f"- `/allow {rule}`" for rule in denied)])
        if self.forge.read_artifact(request_name(ALLOW_KEY)) != text:
            self.forge.request(ALLOW_KEY, text)
        self.waiting = ALLOW_KEY
        return False

    def notify(self, message: str) -> None:
        pass

    def _allowed_on_issue(self) -> list[str]:
        return list(dict.fromkeys(ALLOW.findall("\n".join(self.forge.owner_replies()))))

    def _request(self, key: str, text: str) -> None:
        if not self.forge.has_artifact(request_name(key)):
            self.forge.request(key, text)

    def _decided(self, key: str, text: str) -> bool:
        self._request(key, text)
        decision = self.forge.decision(key)
        if decision is None:
            self.waiting = key
        return decision is not None and decision.command == "approve"

    def _answered(self) -> bool:
        """Gate A is passed by answers, not by a yes: it waits while any escalated question is open."""
        if not escalated_entries(self.forge.read_artifact(GATE_A.artifact) or ""):
            return True
        self._request(GATE_A.key, GATE_A_HELP)
        self.waiting = GATE_A.key
        return False

    def _answer(self, prompt: str) -> str:
        """Answers the escalated question named in `prompt` from the `Q<n>:` replies; `/approve` takes its recommendation."""
        question = QUESTION.search(prompt.splitlines()[0])
        if not question:
            return ""
        answers = dict(ANSWER.findall("\n".join(self.forge.human_comments_after(request_name(GATE_A.key)))))
        decision = self.forge.decision(GATE_A.key)
        return answers.get(question[1]) or ("r" if decision and decision.command == "approve" else "")

    def _head_binding(self) -> str:
        """Withdraws a Gate B request made for another commit, so a reply to it cannot approve newer code."""
        binding = f"Head commit: `{self.forge.head()}`"
        request = self.forge.read_artifact(request_name(GATE_B.key))
        if request is not None and binding not in request:
            self.forge.withdraw(GATE_B.key)
        return binding

    def _take_feedback(self, prompt: str) -> str:
        """Returns `/revise` feedback once, withdrawing the request so the revised code gets a new one."""
        decision = self.forge.decision(GATE_B.key)
        if not decision or decision.command != "revise":
            return ""
        self.forge.withdraw(GATE_B.key)
        return decision.text
