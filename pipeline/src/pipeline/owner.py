from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pipeline.agent import Denial
from pipeline.forge import Forge, request_name

CONVENTION = "convention"
STEP = "step"
REPLY_HELP = "Reply `/approve` to continue or `/reject` to stop, then run the same command again."


class Owner(Protocol):
    """The person who decides at each ask point; `key` names the ask point."""

    asks_on_resume: bool

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
    waiting: str | None = None
    asks_on_resume = True

    def confirm(self, key: str, question: str, details: str = "") -> bool:
        if key == CONVENTION:
            return False
        if not self.forge.has_artifact(request_name(key)):
            self.forge.request(key, "\n\n".join(part for part in (question, details, REPLY_HELP) if part))
        decision = self.forge.decision(key)
        if decision is None:
            self.waiting = key
        return decision is not None and decision.command == "approve"

    def reader(self, key: str) -> Callable[[str], str] | None:
        return None

    def approve(self, denials: tuple[Denial, ...]) -> bool:
        return False

    def notify(self, message: str) -> None:
        pass
