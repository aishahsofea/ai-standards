import re
from collections.abc import Callable
from dataclasses import dataclass

ENTRY_START = r"(?:(?:\d+[.)]|[-*]) |\*\*Q\d)"
ENTRY = re.compile(rf"(?m)^{ENTRY_START}")
ANSWERED = re.compile(r"(?mi)^\s*Answer:\s*(?!_?pending_?\s*$)\S")
PENDING = re.compile(r"(?mi)^(\s*Answer:)\s*_?pending_?\s*$")
REVISIT = re.compile(r"(?mi)^\s*Answer:\s*\[revisit\]")
RECOMMENDATION = re.compile(r"Recommendation:\s*(.+)")
PHASE_HEADING = re.compile(r"^#{2,3} Phase (\d+)(?::\s*(.*))?", re.MULTILINE)


class GateError(Exception):
    pass


@dataclass(frozen=True)
class Gate:
    after: str
    message: str
    artifact: str
    preview: Callable[[str], str]
    publishes: bool = False
    needs_input: Callable[[str], bool] = lambda _: True
    answer: Callable[[str, Callable[[str], str]], str] | None = None
    unresolved: Callable[[str], list[str]] = lambda _: []
    needs_rerun: Callable[[str], bool] = lambda _: False
    revisable: bool = False


def section(text: str, heading: str) -> str:
    match = re.search(rf"^#{{2,3}} {heading}\b.*?(?=^#{{2,3}} |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def escalated_entries(decisions: str) -> list[str]:
    text = section(decisions, "Escalated")
    if not text:
        raise GateError("the decisions comment has no '## Escalated' section")
    entries = re.split(rf"(?m)^(?={ENTRY_START})", text)[1:]
    if not entries and text.splitlines()[1:] and not re.fullmatch(r"\s*None\.?\s*", "\n".join(text.splitlines()[1:])):
        raise GateError("could not read any entries under '## Escalated'; use a numbered or bulleted list")
    return [entry.strip() for entry in entries if not ANSWERED.search(entry)]


def escalated_section(decisions: str) -> str:
    text = section(decisions, "Escalated")
    if not ENTRY.search(text):
        return text
    return "\n".join(["## Escalated", *(escalated_entries(decisions) or ["All answered."])])


def decisions_preview(decisions: str) -> str:
    decided = re.findall(r"(?ms)^#{2,3} Decided\b.*?(?=^#{2,3} |\Z)", decisions)
    return "\n\n".join(part for part in (*(text.strip() for text in decided), escalated_section(decisions)) if part)


def read_reply(entry: str, ask: Callable[[str], str]) -> tuple[str, bool]:
    prompt = (
        f"{entry.splitlines()[0][:80]}\n"
        "Answer (Enter skip, r recommendation, m multi-line, ! first if it changes an earlier decision): "
    )
    reply = ask(prompt).strip()
    revisit = reply.startswith("!")
    reply = reply.removeprefix("!").strip()
    if reply.lower() == "r":
        recommendation = RECOMMENDATION.search(entry)
        reply = recommendation[1].strip() if recommendation else ""
    elif reply.lower() == "m":
        lines = iter(lambda: ask("  > ").rstrip(), "")
        reply = "\n".join(lines).strip()
    return reply, revisit


def answer_escalated(decisions: str, ask: Callable[[str], str]) -> str:
    for entry in escalated_entries(decisions):
        reply, revisit = read_reply(entry, ask)
        if not reply:
            continue
        first, *rest = reply.splitlines()
        text = "\n".join([f"{'[revisit] ' if revisit else ''}{first}", *(f"    {line}" for line in rest)])
        answered = PENDING.sub(lambda m: f"{m[1]} {text}", entry, count=1) if PENDING.search(entry) else f"{entry}\n  Answer: {text}"
        decisions = decisions.replace(entry, answered, 1)
    return decisions


def plan_preview(plan: str) -> str:
    titles = [title.strip() for _, title in PHASE_HEADING.findall(plan)]
    phases = "Phases:\n" + "\n".join(f"{n}. {title}" for n, title in enumerate(titles, 1))
    return "\n\n".join(part for part in (phases, section(plan, "Assumptions"), section(plan, "Out of scope")) if part)


def read_feedback(ask: Callable[[str], str]) -> str:
    reply = ask("What should change? (Enter to stop, m multi-line): ").strip()
    if reply.lower() == "m":
        reply = "\n".join(iter(lambda: ask("  > ").rstrip(), "")).strip()
    return reply


def confirm(question: str, ask: Callable[[str], str] = input) -> bool:
    return ask(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


GATE_A = Gate(
    "decide", "Escalated questions answered in the decisions comment on the issue (edit it or reply). Continue?",
    "decisions", decisions_preview, needs_input=lambda decisions: bool(escalated_entries(decisions)), answer=answer_escalated,
    unresolved=escalated_entries, needs_rerun=lambda decisions: bool(REVISIT.search(decisions)),
)
GATE_B = Gate("docs", "Reviewed the PR text and changes. Mark the PR ready?", "pr", str.strip, publishes=True, revisable=True)
GATES = {gate.after: gate for gate in (GATE_A, GATE_B)}
