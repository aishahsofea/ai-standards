import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pipeline.agent import Agent
from pipeline.cost import CostLedger
from pipeline.gates import GATES
from pipeline.run_dir import RunDir

PHASE_HEADING = re.compile(r"^#{2,3} Phase (\d+)", re.MULTILINE)


@dataclass(frozen=True)
class Stage:
    name: str
    skill: str
    inputs: tuple[str, ...]
    output: str
    model: str
    max_turns: int
    instruction: str = ""


ISSUE = Stage("issue", "forge-cli", (), "issue", "sonnet", 10)
ANALYZE = Stage("analyze", "analyze-issue", ("issue",), "analysis", "opus", 30)
DECIDE = Stage("decide", "decide", ("issue", "analysis"), "decisions", "opus", 30)
PLAN = Stage("plan", "plan", ("issue", "analysis", "decisions"), "plan", "opus", 30)


def phase_count(plan: str) -> int:
    numbers = [int(number) for number in PHASE_HEADING.findall(plan)]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("plan needs sequentially numbered '## Phase N' headings starting at 1")
    return len(numbers)


def phase_summary(phase: int) -> str:
    return f"phase-{phase}-summary"


def phase_stage(phase: int) -> Stage:
    earlier = tuple(phase_summary(n) for n in range(1, phase))
    return Stage(
        f"implement-phase-{phase}", "implement-phase", ("plan", *earlier), phase_summary(phase),
        "sonnet", 60, f"Implement only phase {phase} of the plan.",
    )


def closing_stages(phases: int) -> tuple[Stage, Stage]:
    summaries = tuple(phase_summary(n) for n in range(1, phases + 1))
    return (
        Stage("test", "test", ("plan", *summaries), "test-report", "sonnet", 30),
        Stage("docs", "docs", ("plan", *summaries, "test-report"), "pr", "sonnet", 20),
    )


@dataclass
class Pipeline:
    run_dir: RunDir
    ledger: CostLedger
    agent_for: Callable[[Stage], Agent]
    skills_dir: Path
    idea: str
    confirm: Callable[[str], bool]
    show: Callable[[str], None]
    stop_after: str | None = None
    pause_each: bool = True

    def run(self) -> str | None:
        """Runs stages in order; returns the stage it stopped at, or None when finished."""
        for stage in self._stages():
            ran = self._execute(stage)
            if stage.name == self.stop_after or not self._proceed(stage, ran):
                return stage.name
        return None

    def build_prompt(self, stage: Stage) -> str:
        parts = [
            f"Follow the skill at {self.skills_dir / stage.skill / 'SKILL.md'}.",
            "Run non-interactively; do not ask questions.",
            f"Idea: {self.idea}",
        ]
        if stage.inputs:
            files = "\n".join(f"- {self.run_dir.artifact_path(name)}" for name in stage.inputs)
            parts.append(f"Input files:\n{files}")
        if stage.instruction:
            parts.append(stage.instruction)
        output = self.run_dir.artifact_path(stage.output)
        parts.append(f"Your final reply is saved as {output}; make it the complete document.")
        return "\n".join(parts)

    def _stages(self) -> Iterator[Stage]:
        yield from (ISSUE, ANALYZE, DECIDE, PLAN)
        phases = phase_count(self.run_dir.read(self.run_dir.artifact_path("plan")))
        yield from (phase_stage(n) for n in range(1, phases + 1))
        yield from closing_stages(phases)

    def _execute(self, stage: Stage) -> bool:
        output = self.run_dir.artifact_path(stage.output)
        if self.run_dir.exists(output):
            return False
        self.ledger.check()
        budget = self.ledger.budget_usd - self.ledger.total()
        result = self.agent_for(stage).run(self.build_prompt(stage), stage.model, budget)
        self.ledger.record(stage.name, stage.model, result.cost_usd)
        self.run_dir.write(output, result.text)
        return True

    def _proceed(self, stage: Stage, ran: bool) -> bool:
        if gate := GATES.get(stage.name):
            text = self.run_dir.read(self.run_dir.artifact_path(gate.artifact))
            self.show(gate.preview(text))
            return self.confirm(gate.message)
        return not (ran and self.pause_each) or self.confirm(f"{stage.name} done. Continue?")
