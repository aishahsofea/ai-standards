import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pipeline.agent import Agent
from pipeline.cost import CostLedger
from pipeline.forge import Forge, ForgeError
from pipeline.gates import GATES
from pipeline.run_dir import RunDir

PHASE_HEADING = re.compile(r"^#{2,3} Phase (\d+)", re.MULTILINE)
BLOCKED = re.compile(r"\s*Status:\s*(blocked|fail)", re.IGNORECASE)
Outcome = Literal["skipped", "done", "blocked"]


@dataclass(frozen=True)
class Stage:
    name: str
    skill: str
    inputs: tuple[str, ...]
    output: str
    model: str
    max_turns: int
    instruction: str = ""


ISSUE_INSTRUCTION = (
    "Draft a GitHub issue for the idea: a first line '# <title>', then Problem, "
    "Proposed design and Acceptance criteria sections. Do not create the issue; the pipeline does."
)
ISSUE = Stage("issue", "forge-cli", (), "issue", "sonnet", 10, ISSUE_INSTRUCTION)
ANALYZE = Stage("analyze", "analyze-issue", ("issue",), "analysis", "opus", 30)
DECIDE = Stage("decide", "decide", ("issue", "analysis"), "decisions", "opus", 30)
PLAN = Stage("plan", "plan", ("issue", "analysis", "decisions"), "plan", "opus", 30)


def phase_count(plan: str) -> int:
    numbers = [int(number) for number in PHASE_HEADING.findall(plan)]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("plan needs sequentially numbered '## Phase N' headings starting at 1")
    return len(numbers)


def issue_title(issue: str) -> str:
    first_line = next(line for line in issue.splitlines() if line.strip())
    return first_line.lstrip("# ").strip()


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
    forge: Forge
    stop_after: str | None = None
    pause_each: bool = True

    def run(self) -> str | None:
        """Runs stages in order; returns the stage it stopped at, or None when finished."""
        for stage in self._stages():
            outcome = self._execute(stage)
            if outcome == "done":
                self.forge.checkpoint(stage.name)
            if outcome == "blocked" or stage.name == self.stop_after:
                return stage.name
            if not self._proceed(stage, outcome == "done"):
                return stage.name
        return None

    def build_prompt(self, stage: Stage) -> str:
        parts = [
            f"Follow the skill at {self.skills_dir / stage.skill / 'SKILL.md'}.",
            "Run non-interactively; do not ask questions.",
            f"Idea: {self.idea}",
        ]
        if stage.inputs:
            paths = self.run_dir.stage_inputs({name: self._input(stage, name) for name in stage.inputs})
            parts.append("Input files:\n" + "\n".join(f"- {path}" for path in paths))
        if stage.instruction:
            parts.append(stage.instruction)
        target = "issue body" if stage.output == "issue" else f"{stage.output} comment"
        parts.append(f"Your final reply is posted as the {target}; make it the complete document.")
        return "\n".join(parts)

    def _artifact(self, name: str) -> str:
        text = self.forge.read_artifact(name)
        if text is None:
            raise ForgeError(f"the '{name}' comment is missing from the issue")
        return text

    def _input(self, stage: Stage, name: str) -> str:
        text = self._artifact(name)
        if stage.name == PLAN.name and name == "decisions" and (replies := self.forge.human_comments_after(name)):
            text += "\n\n## Replies on the issue\n\n" + "\n\n".join(replies)
        return text

    def _stages(self) -> Iterator[Stage]:
        yield from (ISSUE, ANALYZE, DECIDE, PLAN)
        phases = phase_count(self._artifact("plan"))
        yield from (phase_stage(n) for n in range(1, phases + 1))
        yield from closing_stages(phases)

    def _execute(self, stage: Stage) -> Outcome:
        if self.forge.has_artifact(stage.output):
            return "skipped"
        self.ledger.check()
        budget = self.ledger.budget_usd - self.ledger.total()
        result = self.agent_for(stage).run(self.build_prompt(stage), stage.model, budget)
        self.ledger.record(stage.name, stage.model, result.cost_usd)
        if BLOCKED.match(result.text):
            blocked = f"{stage.name}.blocked"
            self.show(f"{stage.name} stopped; report posted as the '{blocked}' comment on the issue:\n{result.text}")
            self.forge.post_artifact(blocked, result.text)
            return "blocked"
        if stage.output == ISSUE.output:
            self.forge.open_issue(issue_title(result.text), result.text)
        else:
            self.forge.post_artifact(stage.output, result.text)
        return "done"

    def _proceed(self, stage: Stage, ran: bool) -> bool:
        if gate := GATES.get(stage.name):
            self.show(gate.preview(self._artifact(gate.artifact)))
            approved = self.confirm(gate.message)
            if approved and gate.publishes:
                self.forge.finish(self._artifact(gate.artifact))
            return approved
        return not (ran and self.pause_each) or self.confirm(f"{stage.name} done. Continue?")
