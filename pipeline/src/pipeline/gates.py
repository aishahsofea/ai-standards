import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Gate:
    after: str
    message: str
    artifact: str
    preview: Callable[[str], str]
    publishes: bool = False


def escalated_section(decisions: str) -> str:
    match = re.search(r"^## Escalated\b.*?(?=^## |\Z)", decisions, re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def confirm(question: str, ask: Callable[[str], str] = input) -> bool:
    return ask(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


GATE_A = Gate("decide", "Escalated questions answered in the decisions comment on the issue (edit it or reply). Continue?", "decisions", escalated_section)
GATE_B = Gate("docs", "Reviewed the PR text and changes. Mark the PR ready?", "pr", str.strip, publishes=True)
GATES = {gate.after: gate for gate in (GATE_A, GATE_B)}
