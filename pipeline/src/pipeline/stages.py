import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from itertools import count
from pathlib import Path
from typing import Literal

from pipeline.agent import Agent, Result
from pipeline.checks import CheckRun, baseline_report, failure_sections, known_failures
from pipeline.cost import CostLedger
from pipeline.forge import Check, Forge, ForgeError
from pipeline.gates import GATES, PHASE_HEADING, plan_preview, read_feedback
from pipeline.owner import CONVENTION, STEP, Owner
from pipeline.run_dir import RunDir
from pipeline.validate import analysis_problems, decisions_problems, plan_problems, proposed_convention, reference_problems

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
MAX_FIX_ROUNDS = 2
FIX_NOTE = "This is automatic fix round {round} of {rounds}; if findings remain after the last round, the run stops."
RECHECK_NOTE = "The fix stage changed the code after the review failed. Check the code as it is now."
REREVIEW_NOTE = (
    f"{RECHECK_NOTE} Recheck every finding in review.blocked; drop one only if the code now fixes it "
    "or a reply on the issue accepts it as is."
)
REVISE_NOTE = "Apply this owner feedback to the finished feature, and nothing else:"
REVISION_RECHECK_NOTE = (
    "The revise stage changed the code to apply owner feedback. Check the code as it is now, and treat "
    "the criteria listed in the latest revision as acceptance criteria."
)
DOCS_REFRESH_NOTE = "The revise stage changed the feature after the PR text was written. Rewrite it to match the code as it is now."
CONVENTIONS_FILE = "UX_CONVENTIONS.md"
REPLY_INPUTS = ("decisions", "review.blocked")
CI_FIX_NOTE = "The CI checks failed on the pull request; the failure log is in ci-failure.md. Fix only what the logs show."
CI_RECHECK_NOTE = "The ci-fix stage changed the code after CI failed. Check the code as it is now."
MAX_CI_ROUNDS = 2
BASELINE = "baseline"
PREFLIGHT = "preflight"
MAX_VERIFY_ROUNDS = 2
VERIFY_RETRY = "These checks passed before your change and fail now:\n\n{failures}\n\nFix the cause, then reply with your complete report again."
BASELINE_QUESTION = "These checks fail before any change. Continue and treat them as known failures?"
CI_POLL_S = 15
CI_GRACE_S = 120
CI_TIMEOUT_S = 1800


def ci_summary(checks: list[Check], on_base: set[str]) -> str:
    if not checks:
        return "No CI checks reported for this PR."
    summary = f"CI: no failures caused by this branch ({len(checks)} checks)."
    return f"{summary} Also failing on the base branch, so not fixed: {', '.join(sorted(on_base))}." if on_base else summary


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


STATUS_RETRY = "Reply with your report only. The first line must be `Status: {allowed}`."
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


def ci_fix_stage(number: int) -> Stage:
    return Stage(
        "ci-fix", "ci-fix", ("issue", "plan", "test-report", "ci-failure"), f"ci-fix-{number}", "sonnet", 40,
        "Diagnose and fix the failing CI checks.", ("done", "rerun", "blocked"), "pipeline: fix CI failures",
    )


def revise_stage(number: int, inputs: tuple[str, ...]) -> Stage:
    return Stage(
        "revise", "revise", inputs, f"revision-{number}", "sonnet", 60,
        statuses=("done", "blocked"), commit=f"revise {number}: apply owner feedback",
    )


@dataclass
class Pipeline:
    run_dir: RunDir
    ledger: CostLedger
    agent_for: Callable[[Stage], Agent]
    skills_dir: Path
    idea: str
    owner: Owner
    show: Callable[[str], None]
    forge: Forge
    stop_after: str | None = None
    pause_each: bool = False
    checks: Callable[[], list[CheckRun]] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    ci_timeout_s: float = CI_TIMEOUT_S

    def run(self) -> str | None:
        """Runs stages in order; returns the stage it stopped at, or None when finished."""
        stages: dict[str, Stage] = {}
        for stage in self._stages():
            stages[stage.name] = stage
            if stage.name == ANALYZE.name and not self._preflight():
                return PREFLIGHT
            outcome = "blocked" if self._review_failed_earlier(stage) else self._execute(stage)
            if outcome == "blocked" and stage.name == "review":
                if stopped := self._fix_round(stages["test"], stage):
                    return stopped
                outcome = "done"
            if outcome == "done":
                self.forge.checkpoint(stage.commit or f"pipeline: {stage.name}")
            if outcome == "blocked" or stage.name == self.stop_after:
                return stage.name
            if stage.name == "docs" and (stopped := self._ci_round(stages["test"])):
                return stopped
            if not self._proceed(stage, outcome == "done"):
                return stage.name
        return None

    def build_prompt(self, stage: Stage, note: str = "") -> str:
        parts = [
            f"Follow the skill at {self.skills_dir / stage.skill / 'SKILL.md'}.",
            "Run non-interactively; do not ask questions.",
            f"Idea: {self.idea}",
        ]
        if inputs := self._inputs(stage):
            paths = self.run_dir.stage_inputs({name: self._input(stage, name) for name in inputs})
            parts.append("Input files:\n" + "\n".join(f"- {path}" for path in paths))
        if stage.instruction:
            parts.append(stage.instruction)
        if note:
            parts.append(note)
        target = "issue body" if stage.output == "issue" else f"{stage.output} comment"
        parts.append(f"Your final reply is posted as the {target}; make it the complete document.")
        return "\n".join(parts)

    def _inputs(self, stage: Stage) -> tuple[str, ...]:
        """Stages that run the repo's checks also read the baseline, when the preflight posted one."""
        runs_checks = stage.statuses and not stage.read_only
        return (*stage.inputs, BASELINE) if runs_checks and self.forge.has_artifact(BASELINE) else stage.inputs

    def _preflight(self) -> bool:
        """Runs the repo's checks before the first change; False when the owner declines to go on past failures."""
        if not self.checks or self.forge.has_artifact(BASELINE) or self.forge.has_artifact(ANALYZE.output):
            return True
        self.show("preflight: running the repo's checks before any change")
        runs = self.checks()
        report = baseline_report(runs)
        self.show(report)
        if not all(run.ok for run in runs):
            self.owner.notify("preflight found failing checks")
            if not self.owner.confirm(BASELINE, BASELINE_QUESTION, report):
                return False
        self.forge.post_artifact(BASELINE, report)
        return True

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
        result = self._verified(stage, prompt, self._with_status(stage, prompt, self._run(stage, prompt)))
        report = self._blocked_report(stage, result.text)
        if not report and (problems := self._problems(stage, result.text)):
            result = self._run(stage, retry_prompt(prompt, result.text, problems))
            report = self._blocked_report(stage, result.text)
            if not report and (problems := self._problems(stage, result.text)):
                report = f"Status: blocked - the reply failed these checks:\n{bullets(problems)}\n\n{result.text}"
        if report and result.denials and self.owner.approve(result.denials):
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

    def revise(self, feedback: str) -> str | None:
        """Applies owner feedback, rechecks, rewrites the PR text and asks Gate B again; returns the stage it stopped at, or None when finished."""
        phases = phase_count(self._artifact("plan"))
        earlier = tuple(name for n in range(1, 100) if self.forge.has_artifact(name := f"revision-{n}"))
        context = ("issue", "plan", *map(phase_summary, range(1, phases + 1)), "test-report", "test.blocked", "review", "review.blocked", "pr", *earlier)
        stage = revise_stage(len(earlier) + 1, tuple(name for name in context if self.forge.has_artifact(name)))
        test, review, docs = closing_stages(phases)
        rechecks = (
            (stage, f"{REVISE_NOTE}\n{feedback}"),
            (replace(test, inputs=(*test.inputs, stage.output)), REVISION_RECHECK_NOTE),
            (replace(review, inputs=(*review.inputs, stage.output)), REVISION_RECHECK_NOTE),
            (replace(docs, inputs=(*docs.inputs, stage.output)), DOCS_REFRESH_NOTE),
        )
        for step, note in rechecks:
            if self._execute(step, note) == "blocked":
                return step.name
            if step is stage:
                self._offer_convention(self._artifact(stage.output))
            self.forge.checkpoint(step.commit or f"pipeline: {step.name}")
        if stopped := self._ci_round(test):
            return stopped
        return None if self._proceed(docs, True) else docs.name

    def _offer_convention(self, revision: str) -> None:
        rule = proposed_convention(revision)
        path = self.run_dir.repo / CONVENTIONS_FILE
        if not rule or (path.exists() and rule in path.read_text()):
            return
        self.show(f"Proposed convention for {CONVENTIONS_FILE}:\n- {rule}")
        if self.owner.confirm(CONVENTION, f"Append it to {CONVENTIONS_FILE}?"):
            existing = path.read_text() if path.exists() else ""
            if existing and not existing.endswith("\n"):
                existing += "\n"
            path.write_text(f"{existing}- {rule}\n")

    def _fix_round(self, test: Stage, review: Stage) -> str | None:
        """Runs fix, test and review after a failed review, up to MAX_FIX_ROUNDS times; returns the stage it stopped at, or None once the review passes."""
        review = replace(review, inputs=(*review.inputs, "review.blocked", FIX.output))
        for number in range(1, MAX_FIX_ROUNDS + 1):
            self.show(f"review failed; running fix round {number} of {MAX_FIX_ROUNDS}")
            for stage in (FIX, test):
                note = FIX_NOTE.format(round=number, rounds=MAX_FIX_ROUNDS) if stage is FIX else RECHECK_NOTE
                if self._execute(stage, note) == "blocked":
                    return stage.name
                self.forge.checkpoint(stage.commit or f"pipeline: {stage.name}")
            if self._execute(review, REREVIEW_NOTE) == "done":
                return None
        return review.name

    def _ci_round(self, test: Stage) -> str | None:
        """Waits for the PR's checks and fixes failures; returns the stage it stopped at, or None when CI is green or absent."""
        for attempt in range(MAX_CI_ROUNDS + 1):
            self.show("waiting for CI checks")
            checks = self._wait_for_ci()
            if checks is None:
                return self._ci_blocked(f"checks did not finish within {self.ci_timeout_s:.0f}s")
            failing = [check for check in checks if check.state == "fail"]
            on_base = {check.name for check in failing} & self.forge.base_failures() if failing else set()
            failing = [check for check in failing if check.name not in on_base]
            if not failing:
                self.show(ci_summary(checks, on_base))
                return None
            names = ", ".join(check.name for check in failing)
            if attempt == MAX_CI_ROUNDS:
                return self._ci_blocked(f"still failing after {MAX_CI_ROUNDS} fix rounds: {names}")
            self.show(f"CI failed: {names}")
            self.forge.post_artifact("ci-failure", self.forge.ci_logs(failing))
            fix = ci_fix_stage(next(n for n in count(1) if not self.forge.has_artifact(f"ci-fix-{n}")))
            if self._execute(fix, CI_FIX_NOTE) == "blocked":
                return fix.name
            if (status := STATUS.match(self._artifact(fix.output))) and status[1].lower() == "rerun":
                self.forge.rerun_checks(failing)
                continue
            self.forge.checkpoint(fix.commit)
            if self._execute(test, CI_RECHECK_NOTE) == "blocked":
                return test.name
            self.forge.checkpoint(f"pipeline: {test.name}")
        return None

    def _wait_for_ci(self) -> list[Check] | None:
        """Polls until no check is pending; None on timeout. Zero checks counts only after a grace period."""
        start = self.clock()
        while (elapsed := self.clock() - start) < self.ci_timeout_s:
            checks = self.forge.ci_checks()
            if checks is not None and all(check.state != "pending" for check in checks) and (checks or elapsed >= CI_GRACE_S):
                return checks
            self.sleep(CI_POLL_S)
        return None

    def _ci_blocked(self, report: str) -> str:
        self.show(f"CI check stopped; report posted as the 'ci.blocked' comment on the issue:\n{report}")
        self.forge.post_artifact("ci.blocked", report)
        return "ci"

    def _ci_fixes(self) -> str:
        summaries = []
        for n in count(1):
            if not self.forge.has_artifact(name := f"ci-fix-{n}"):
                break
            summaries.append(self._artifact(name).partition("\n")[2].strip())
        return "\n\n## CI fixes\n\n" + "\n\n".join(summaries) if summaries else ""

    def _review_failed_earlier(self, stage: Stage) -> bool:
        """A resumed run sends an earlier failed review to the fix round instead of reviewing afresh."""
        if stage.name != "review" or self.forge.has_artifact(stage.output):
            return False
        report = self.forge.read_artifact("review.blocked")
        return report is not None and (match := STATUS.match(report)) is not None and match[1].lower() == "fail"

    def _run(self, stage: Stage, prompt: str, resume: Result | None = None) -> Result:
        self.ledger.check()
        result = self.agent_for(stage).run(prompt, stage.model, self.ledger.budget_usd - self.ledger.total(), resume=resume)
        self.ledger.record(stage.name, stage.model, result.cost_usd)
        return result

    def _verified(self, stage: Stage, prompt: str, result: Result) -> Result:
        """Runs the repo's checks after a stage reports done and sends new failures back to its session; blocks the stage if they persist."""
        for attempt in range(MAX_VERIFY_ROUNDS + 1):
            if not (failing := self._new_failures(stage, result)):
                return result
            failures = failure_sections(failing)
            if attempt == MAX_VERIFY_ROUNDS:
                break
            self.show(f"{stage.name}: checks fail after the change; sending them back ({attempt + 1} of {MAX_VERIFY_ROUNDS})")
            if result.session_id:
                repair = self._run(stage, VERIFY_RETRY.format(failures=failures), resume=result)
            else:
                repair = self._run(stage, f"{prompt}\n\n{VERIFY_RETRY.format(failures=failures)}")
            repair = self._with_status(stage, prompt, repair)
            result = replace(repair, denials=(*result.denials, *repair.denials))
        return replace(result, text=f"Status: blocked - checks still fail after {MAX_VERIFY_ROUNDS} repair rounds\n\n{failures}\n\n{result.text}")

    def _new_failures(self, stage: Stage, result: Result) -> list[CheckRun]:
        """Checks that fail now and passed in the baseline; empty unless the stage reports `done` and a baseline exists."""
        status = STATUS.match(result.text)
        if not (self.checks and status and status[1].lower() == "done" and "done" in stage.statuses):
            return []
        if (baseline := self.forge.read_artifact(BASELINE)) is None:
            return []
        known = known_failures(baseline)
        return [run for run in self.checks() if not run.ok and run.command not in known]

    def _with_status(self, stage: Stage, prompt: str, result: Result) -> Result:
        """Asks once more when the reply's first-line status is missing or not allowed for the stage."""
        status = STATUS.match(result.text)
        if not stage.statuses or (status and status[1].lower() in stage.statuses):
            return result
        allowed = "|".join(stage.statuses)
        if result.session_id:
            retry = self._run(stage, STATUS_RETRY.format(allowed=allowed), resume=result)
        else:
            retry = self._run(stage, retry_prompt(prompt, result.text, [f"the first line must be `Status: {allowed}`"]))
        return replace(retry, denials=(*result.denials, *retry.denials))

    def _problems(self, stage: Stage, text: str) -> list[str]:
        if stage.name == ANALYZE.name:
            return analysis_problems(text, self._artifact("issue")) + reference_problems(text, self.run_dir.repo)
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
            if gate.publishes and (screenshots := self.run_dir.screenshots()):
                self.show("Screenshots to review:\n" + bullets([str(path) for path in screenshots]))
            self.owner.notify(f"{stage.name} is waiting for your review")
            ask = self.owner.reader(gate.key)
            if ask and gate.answer and (updated := gate.answer(artifact, ask)) != artifact:
                self.forge.post_artifact(gate.artifact, updated)
                if gate.needs_rerun(updated):
                    if self._execute(replace(stage, inputs=(*stage.inputs, gate.artifact)), REVISIT_NOTE) == "blocked":
                        return False
                    self.show(gate.preview(self._artifact(gate.artifact)))
            approved = self.owner.confirm(gate.key, gate.message)
            if not approved and gate.revisable and ask and (feedback := read_feedback(ask)):
                return self.revise(feedback) is None
            if approved and (open_items := gate.unresolved(self._artifact(gate.artifact))):
                self.show(f"{len(open_items)} escalated question(s) still have no answer; answer them, then --resume.")
                return False
            if approved and gate.publishes:
                self.forge.finish(self._artifact(gate.artifact) + self._ci_fixes())
            return approved
        question = f"{stage.name} done. Continue?"
        if stage.name == PLAN.name and (ran or self.owner.asks_on_resume):
            self.show(plan_preview(self._artifact(PLAN.output)))
            self.owner.notify("plan is waiting for your review")
            return self.owner.confirm(PLAN.name, question)
        return not (ran and self.pause_each) or self.owner.confirm(STEP, question)
