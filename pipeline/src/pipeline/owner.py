from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pipeline.agent import Denial

CONVENTION = "convention"
STEP = "step"


class Owner(Protocol):
    """The person who decides at each ask point; `key` names the ask point."""

    def confirm(self, key: str, question: str) -> bool: ...
    def reader(self, key: str) -> Callable[[str], str] | None: ...
    def approve(self, denials: tuple[Denial, ...]) -> bool: ...
    def notify(self, message: str) -> None: ...


@dataclass
class TerminalOwner:
    ask_yes_no: Callable[[str], bool]
    read_line: Callable[[str], str] | None = None
    allow: Callable[[tuple[Denial, ...]], bool] | None = None
    alert: Callable[[str], None] = lambda _: None

    def confirm(self, key: str, question: str) -> bool:
        return self.ask_yes_no(question)

    def reader(self, key: str) -> Callable[[str], str] | None:
        return self.read_line

    def approve(self, denials: tuple[Denial, ...]) -> bool:
        return bool(self.allow and self.allow(denials))

    def notify(self, message: str) -> None:
        self.alert(message)
