from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class AgentError(Exception):
    pass


@dataclass(frozen=True)
class Denial:
    tool: str
    command: str = ""

    @property
    def rule(self) -> str:
        if self.tool != "Bash":
            return self.tool
        words = self.command.split()
        prefix = words[:2] if len(words) > 1 and not words[1].startswith("-") else words[:1]
        return f"Bash({' '.join(prefix)}:*)"


@dataclass(frozen=True)
class Result:
    text: str
    cost_usd: float
    denials: tuple[Denial, ...] = ()


class Agent(Protocol):
    def run(self, prompt: str, model: str, budget: float) -> Result: ...


class FakeAgent:
    def __init__(self, respond: Callable[[str], str] = lambda prompt: "ok", cost_usd: float = 0.0) -> None:
        self.respond = respond
        self.cost_usd = cost_usd
        self.calls: list[tuple[str, str, float]] = []

    def run(self, prompt: str, model: str, budget: float) -> Result:
        self.calls.append((prompt, model, budget))
        return Result(self.respond(prompt), self.cost_usd)
