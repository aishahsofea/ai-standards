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
    session_id: str = ""
    session_cost_usd: float = 0.0


class Agent(Protocol):
    def run(self, prompt: str, model: str, budget: float, resume: Result | None = None) -> Result: ...


class FakeAgent:
    def __init__(self, respond: Callable[[str], str] = lambda prompt: "ok", cost_usd: float = 0.0) -> None:
        self.respond = respond
        self.cost_usd = cost_usd
        self.calls: list[tuple[str, str, float]] = []
        self.resumes: list[tuple[str, str]] = []

    def run(self, prompt: str, model: str, budget: float, resume: Result | None = None) -> Result:
        self.calls.append((prompt, model, budget))
        if resume:
            self.resumes.append((prompt, resume.session_id))
        session_id = resume.session_id if resume else f"fake-{len(self.calls)}"
        return Result(self.respond(prompt), self.cost_usd, session_id=session_id)
