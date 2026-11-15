import re
import select
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from concierge.notifier import Choice

TARGET = re.compile(r"@(\d+)\s+(.+)")


@dataclass(frozen=True)
class Event:
    kind: str
    text: str = ""
    data: str = ""
    message_id: str | None = None
    audio: bytes = b""


class Chat(Protocol):
    def send(self, text: str, choices: tuple[Choice, ...] = (), silent: bool = False) -> str: ...
    def poll(self, timeout: float) -> list[Event]: ...


def read_stdin_line(timeout: float) -> str | None:
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.readline() if ready else None


class StdinChat:
    """A terminal stand-in for a chat app: numbered choices are the buttons, `@<id> ...` replies to a message."""

    def __init__(self, read_line: Callable[[float], str | None] = read_stdin_line, out: Callable[[str], None] = print) -> None:
        self.read_line = read_line
        self.out = out
        self.count = 0
        self.choices: dict[str, tuple[Choice, ...]] = {}

    def send(self, text: str, choices: tuple[Choice, ...] = (), silent: bool = False) -> str:
        self.count += 1
        message_id = str(self.count)
        if choices:
            self.choices[message_id] = choices
        self.out("\n".join([f"[{message_id}] {text}", *(f"  {n}) {choice.label}" for n, choice in enumerate(choices, 1))]))
        return message_id

    def poll(self, timeout: float) -> list[Event]:
        line = (self.read_line(timeout) or "").strip()
        if not line:
            return []
        target = TARGET.fullmatch(line)
        message_id, text = (target[1], target[2]) if target and 1 <= int(target[1]) <= self.count else (None, line)
        if text.isdigit():
            chosen = message_id or max(self.choices, key=int, default="")
            options = self.choices.get(chosen, ())
            if 1 <= int(text) <= len(options):
                return [Event("button", data=options[int(text) - 1].data, message_id=chosen)]
        return [Event("text", text=text, message_id=message_id)]
