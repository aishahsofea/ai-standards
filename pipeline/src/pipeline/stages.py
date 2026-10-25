import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pipeline.agent import Agent, Denial, Result
from pipeline.cost import CostLedger
from pipeline.forge import Forge, ForgeError
from pipeline.gates import GATES, PHASE_HEADING, plan_preview
from pipeline.run_dir import RunDir
from pipeline.validate import analysis_problems, decisions_problems, plan_problems, reference_problems

STATUS = re.compile(r"\s*Status:\s*(\w+)", re.IGNORECASE)
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
    statuses: tuple[str, ...] = ()
    commit: str = ""
    read_only: bool = False


ISSUE_INSTRUCTION = (
    "Draft a GitHub issue for the idea: a first line '# <title>', then Problem, "
    "Proposed design and Acceptance criteria sections. Do not create the issue; the pipeline does."
)
ISSUE = Stage("issue", "forge-cli", (), "issue", "sonnet", 10, ISSUE_INSTRUCTION)
ANALYZE = Stage("analyze", "analyze", ("issue",), "analysis", "opus", 30)
DECIDE = Stage("decide", "decide", ("issue", "analysis"), "decisions", "opus", 30)
PLAN = Stage("plan", "plan", ("issue", "analysis", "decisions"), "plan", "opus", 30)
FIX = Stage(
    "fix", "fix", ("issue", "plan", "test-report", "review.blocked"), "fix-summary", "sonnet", 60,
    "Fix the Critical and Required findings in the failed review.", ("done", "blocked"), "pipeline: fix review findings",
)
FIX_NOTE = "This is the only automatic fix round; if findings remain, the run stops."
RECHECK_NOTE = "The fix stage changed the code after the review failed. Check the code as it is now."
REREVIEW_NOTE = (
    f"{RECHECK_NOTE} Recheck every finding in review.blocked; drop one only if the code now fixes it "
    "or a reply on the issue accepts it as is."
)
REPLY_INPUTS = ("decisions", "review.blocked")


def phase_count(plan: str) -> int:
    numbers = [int(number) for number, _ in PHASE_HEADING.findall(plan)]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("plan needs sequentially numbered '## Phase N' headings starting at 1")
    return len(numbers)


def phase_titles(plan: str) -> list[str]:
    return [title.strip() for _, title in PHASE_HEADING.findall(plan)]


def issue_title(issue: str) -> str:
    first_line = next(line for line in issue.splitlines() if line.strip())
    return first_line.lstrip("# ").strip()


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def retry_prompt(prompt: str, reply: str, problems: list[str]) -> str:
    return f"{prompt}\n\nYour previous reply failed these checks:\n{bullets(problems)}\nFix them and reply with the complete document.\n\nPrevious reply:\n{reply}"


REVISIT_NOTE = (
    "A human answered the escalated questions in the decisions file. Revise only the decisions their "
    "answers change, keep every answer verbatim, and remove each '[revisit]' marker."
)


def phase_summary(phase: int) -> str:
    return f"phase-{phase}-summary"


def phase_stage(phase: int, title: str = "") -> Stage:
    earlier = tuple(phase_summary(n) for n in range(1, phase))
    return Stage(
        f"implement-phase-{phase}", "implement-phase", ("plan", *earlier), phase_summary(phase),
        "sonnet", 60, f"Implement only phase {phase} of the plan.", ("done", "blocked"),
        f"phase {phase}: {title}" if title else "",
    )


def closing_stages(phases: int) -> tuple[Stage, Stage, Stage]:
    summaries = tuple(phase_summary(n) for n in range(1, phases + 1))
    return (
        Stage("test", "test", ("plan", *summaries), "test-report", "sonnet", 30, statuses=("pass", "fail")),
        Stage(
            "review", "review", ("issue", "plan", *summaries, "test-report"), "review", "opus", 30,
            statuses=("pass", "fail"), read_only=True,
        ),
        Stage("docs", "docs", ("plan", *summaries, "test-report", "review"), "pr", "sonnet", 20),
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
    ask: Callable[[str], str] | None = None
    approve: Callable[[tuple[Denial, ...]], bool] | None = None

    def run(self) -> str | None:
        """Runs stages in order; returns the stage it stopped at, or None when finished."""
        stages: dict[str, Stage] = {}
        for stage in self._stages():
            stages[stage.name] = stage
            outcome = "blocked" if self._review_failed_earlier(stage) else self._execute(stage)
            if outcome == "blocked" and stage.name == "review":
                if stopped := self._fix_round(stages["test"], stage):
                    return stopped
                outcome = "done"
            if outcome == "done":
                self.forge.checkpoint(stage.commit or f"pipeline: {stage.name}")
            if outcome == "blocked" or stage.name == self.stop_after:
                return stage.name
            if not self._proceed(stage, outcome == "done"):
                return stage.name
        return None

    def build_prompt(self, stage: Stage, note: str = "") -> str:
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
        if note:
            parts.append(note)
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
        if name in REPLY_INPUTS and (replies := self.forge.human_comments_after(name)):
            text += "\n\n## Replies on the issue\n\n" + "\n\n".join(replies)
        return text

    def _stages(self) -> Iterator[Stage]:
        yield from (ISSUE, ANALYZE, DECIDE, PLAN)
        phases = phase_count(self._artifact("plan"))
        yield from (phase_stage(n, title) for n, title in enumerate(phase_titles(self._artifact("plan")), 1))
        yield from closing_stages(phases)

    def _execute(self, stage: Stage, note: str = "") -> Outcome:
        if not note and self.forge.has_artifact(stage.output):
            return "skipped"
        prompt = self.build_prompt(stage, note)
        result = self._run(stage, prompt)
        report = self._blocked_report(stage, result.text)
        if not report and (problems := self._problems(stage, result.text)):
            result = self._run(stage, retry_prompt(prompt, result.text, problems))
            report = self._blocked_report(stage, result.text)
            if not report and (problems := self._problems(stage, result.text)):
                report = f"Status: blocked - the reply failed these checks:\n{bullets(problems)}\n\n{result.text}"
        if report and self.approve and result.denials and self.approve(result.denials):
            return self._execute(stage, note)
        if report:
            blocked = f"{stage.name}.blocked"
            self.show(f"{stage.name} stopped; report posted as the '{blocked}' comment on the issue:\n{report}")
            self.forge.post_artifact(blocked, report)
            return "blocked"
        if stage.output == ISSUE.output:
            self.forge.open_issue(issue_title(result.text), result.text)
        else:
            self.forge.post_artifact(stage.output, result.text)
        return "done"

    def _fix_round(self, test: Stage, review: Stage) -> str | None:
        """Runs fix, test and review once after a failed review; returns the stage it stopped at, or None if the review passes."""
        self.show("review failed; running one fix round")
        review = replace(review, inputs=(*review.inputs, "review.blocked", FIX.output))
        for stage, note in ((FIX, FIX_NOTE), (test, RECHECK_NOTE), (review, REREVIEW_NOTE)):
            if self._execute(stage, note) == "blocked":
                return stage.name
            if stage is not review:
                self.forge.checkpoint(stage.commit or f"pipeline: {stage.name}")
        return None

    def _review_failed_earlier(self, stage: Stage) -> bool:
        """A resumed run sends an earlier failed review to the fix round instead of reviewing afresh."""
        if stage.name != "review" or self.forge.has_artifact(stage.output):
            return False
        report = self.forge.read_artifact("review.blocked")
        return report is not None and (match := STATUS.match(report)) is not None and match[1].lower() == "fail"

    def _run(self, stage: Stage, prompt: str) -> Result:
        self.ledger.check()
        result = self.agent_for(stage).run(prompt, stage.model, self.ledger.budget_usd - self.ledger.total())
        self.ledger.record(stage.name, stage.model, result.cost_usd)
        return result

    def _problems(self, stage: Stage, text: str) -> list[str]:
        if stage.name == ANALYZE.name:
            return analysis_problems(text) + reference_problems(text, self.run_dir.repo)
        if stage.name == DECIDE.name:
            return decisions_problems(text, self._artifact("analysis")) + reference_problems(text, self.run_dir.repo)
        if stage.name == PLAN.name:
            return plan_problems(text)
        return []

    @staticmethod
    def _blocked_report(stage: Stage, text: str) -> str | None:
        match = STATUS.match(text)
        status = match[1].lower() if match else None
        if not stage.statuses:
            return text if status in ("blocked", "fail") else None
        if status not in stage.statuses:
            allowed = "|".join(stage.statuses)
            return f"Status: blocked - reply must start with `Status: {allowed}`\n\n{text}"
        return text if status == stage.statuses[-1] else None

    def _proceed(self, stage: Stage, ran: bool) -> bool:
        if gate := GATES.get(stage.name):
            artifact = self._artifact(gate.artifact)
            if not ran and not gate.needs_input(artifact):
                return True
            self.show(gate.preview(artifact))
            if self.ask and gate.answer and (updated := gate.answer(artifact, self.ask)) != artifact:
                self.forge.post_artifact(gate.artifact, updated)
                if gate.needs_rerun(updated):
                    if self._execute(replace(stage, inputs=(*stage.inputs, gate.artifact)), REVISIT_NOTE) == "blocked":
                        return False
                    self.show(gate.preview(self._artifact(gate.artifact)))
            approved = self.confirm(gate.message)
            if approved and (open_items := gate.unresolved(self._artifact(gate.artifact))):
                self.show(f"{len(open_items)} escalated question(s) still have no answer; answer them, then --resume.")
                return False
            if approved and gate.publishes:
                self.forge.finish(self._artifact(gate.artifact))
            return approved
        if not (ran and self.pause_each):
            return True
        if stage.name == PLAN.name:
            self.show(plan_preview(self._artifact(PLAN.output)))
        return self.confirm(f"{stage.name} done. Continue?")
