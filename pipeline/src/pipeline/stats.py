import re
from collections import Counter
from dataclasses import dataclass

from pipeline.cost import prior_total
from pipeline.forge import MARKER, comment_text

BLOCKED = ".blocked"
REVISION = re.compile(r"revision-\d+")
PHASE = re.compile(r"-\d+$")
REASON_CHARS = 140


@dataclass(frozen=True)
class RunStats:
    number: int
    title: str
    blocked: dict[str, str]
    revisions: int
    cost_usd: float


def reason(report: str) -> str:
    """The status line, plus the next line when the status gives no reason of its own."""
    first, *rest = [line.strip() for line in report.splitlines() if line.strip()] or [""]
    return first if " - " in first or not rest else f"{first}: {rest[0]}"


def run_stats(issue: dict) -> RunStats:
    """Reads one issue's stage comments; `blocked` maps each stopped stage to the reason in its report."""
    artifacts = {match[1]: comment_text(match[1], c["body"]) for c in issue["comments"] if (match := MARKER.match(c["body"]))}
    blocked = {name.removesuffix(BLOCKED): reason(text) for name, text in artifacts.items() if name.endswith(BLOCKED)}
    revisions = sum(1 for name in artifacts if REVISION.fullmatch(name))
    return RunStats(issue["number"], issue["title"], blocked, revisions, prior_total(artifacts.get("cost")))


def render_stats(runs: list[RunStats]) -> str:
    if not runs:
        return "No pipeline runs found."
    lines = ["| issue | stopped at | revisions | cost |", "|---|---|---|---|"]
    lines += [f"| #{run.number} {run.title[:50]} | {', '.join(run.blocked) or '-'} | {run.revisions} | ${run.cost_usd:.2f} |" for run in runs]
    stopped = [run for run in runs if run.blocked]
    lines += ["", f"{len(runs)} runs, {len(stopped)} stopped at least once, ${sum(run.cost_usd for run in runs):.2f} spent."]
    by_stage = Counter(stage for run in runs for stage in {PHASE.sub("", name) for name in run.blocked})
    if by_stage:
        lines += ["", "Runs stopped, by stage:", *(f"- {stage}: {count}" for stage, count in by_stage.most_common())]
        lines += ["", "Reasons:", *(f"- #{run.number} {stage}: {reason[:REASON_CHARS]}" for run in stopped for stage, reason in run.blocked.items())]
    return "\n".join(lines)
