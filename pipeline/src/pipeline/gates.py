import re
from collections.abc import Callable
from dataclasses import dataclass

PHASE_HEADING = re.compile(r"^#{2,3} Phase (\d+)(?::\s*(.*))?", re.MULTILINE)


@dataclass(frozen=True)
class Gate:
    after: str
    message: str
    artifact: str
    preview: Callable[[str], str]
    publishes: bool = False


def section(text: str, heading: str) -> str:
    match = re.search(rf"^## {heading}\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def escalated_section(decisions: str) -> str:
    return section(decisions, "Escalated")


def plan_preview(plan: str) -> str:
    titles = [title.strip() for _, title in PHASE_HEADING.findall(plan)]
    phases = "Phases:\n" + "\n".join(f"{n}. {title}" for n, title in enumerate(titles, 1))
    return "\n\n".join(part for part in (phases, section(plan, "Assumptions"), section(plan, "Out of scope")) if part)


def confirm(question: str, ask: Callable[[str], str] = input) -> bool:
    return ask(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


GATE_A = Gate("decide", "Escalated questions answered in the decisions comment on the issue (edit it or reply). Continue?", "decisions", escalated_section)
GATE_B = Gate("docs", "Reviewed the PR text and changes. Mark the PR ready?", "pr", str.strip, publishes=True)
GATES = {gate.after: gate for gate in (GATE_A, GATE_B)}
