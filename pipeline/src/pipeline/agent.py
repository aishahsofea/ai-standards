from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class AgentError(Exception):
    pass


@dataclass(frozen=True)
class Result:
    text: str
    cost_usd: float


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
