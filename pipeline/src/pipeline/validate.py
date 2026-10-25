import re
from pathlib import Path

from pipeline.gates import PHASE_HEADING, GateError, escalated_entries, section

QUESTION = re.compile(r"(?m)^[\s\-*\d.)]*\**(Q\d+)\b")
REFERENCE = re.compile(r"`([\w@+-]*[./][\w@./+-]*):(\d+)(?:-(\d+))?`")
NONE = re.compile(r"(?mi)^\W*None\.?\s*$")
VERIFY = re.compile(r"(?m)^\W*Verify:(.*)$")
CONVENTION = re.compile(r"(?m)^[-*] \*\*Proposed convention\*\*\W*(.+)$")
BULLET = re.compile(r"(?m)^\s*[-*] (.+)$")
UI_CHANGE = re.compile(r"(?i)\b(button|sidebar|control|menu|icon)s?\b")
PATTERN = re.compile(r"(?i)\b(modal|dialog|inline|toast|banner|popover|popup|placement|interaction pattern)s?\b")


def question_ids(text: str) -> list[str]:
    return list(dict.fromkeys(QUESTION.findall(text)))


def reference_problems(text: str, repo: Path) -> list[str]:
    problems = []
    for path, first, last in dict.fromkeys(REFERENCE.findall(text)):
        file = repo / path
        if not file.is_file():
            problems.append(f"`{path}` does not exist")
        elif int(last or first) > len(file.read_text(errors="ignore").splitlines()):
            problems.append(f"`{path}:{last or first}` is past the end of the file")
    return problems


def analysis_problems(analysis: str, issue: str = "") -> list[str]:
    questions = section(analysis, "Open questions")
    if not questions:
        return ["missing a '## Open questions' section"]
    if not question_ids(questions) and not NONE.search(questions):
        return ["number each open question Q1, Q2, ... or write 'None.' under '## Open questions'"]
    if UI_CHANGE.search(issue) and not PATTERN.search(issue) and not PATTERN.search(questions):
        return ["the issue changes the UI without fixing the interaction pattern; raise an open question on it (modal vs inline, toast vs banner, placement)"]
    return []


def decisions_problems(decisions: str, analysis: str) -> list[str]:
    problems = [f"missing a '## {heading}' section" for heading in ("Decided from evidence", "Decided, low stakes") if not section(decisions, heading)]
    try:
        escalated_entries(decisions)
    except GateError as error:
        problems.append(str(error))
    if unanswered := [id for id in question_ids(section(analysis, "Open questions")) if id not in question_ids(decisions)]:
        problems.append(f"no decision for {', '.join(unanswered)}")
    return problems


def plan_problems(plan: str) -> list[str]:
    phases = [int(number) for number, _ in PHASE_HEADING.findall(plan)]
    if not phases or phases != list(range(1, len(phases) + 1)):
        return ["number the phases '## Phase 1', '## Phase 2', ... from 1 with no gaps"]
    problems = []
    for number, body in enumerate(re.split(r"(?m)^#{2,3} Phase \d+.*$", plan)[1:], 1):
        verify = VERIFY.search(body)
        if not verify:
            problems.append(f"phase {number} has no Verify: line")
        elif "manual" in verify[1].lower():
            problems.append(f"phase {number}'s Verify: line has a manual step; move it to a 'Manual checks:' line")
    criteria = section(plan, "Acceptance criteria")
    if not criteria:
        return [*problems, "missing a '## Acceptance criteria' section mapping each criterion to a phase"]
    entries = BULLET.findall(criteria)
    if not entries and not NONE.search(criteria):
        problems.append("list each acceptance criterion as a bullet under '## Acceptance criteria'")
    for entry in entries:
        covering = [int(number) for number in re.findall(r"\bPhase (\d+)\b", entry)]
        if not covering and "Manual:" not in entry:
            problems.append(f"no phase covers acceptance criterion: {entry[:80]}")
        elif any(number not in phases for number in covering):
            problems.append(f"acceptance criterion names a phase that does not exist: {entry[:80]}")
    return problems


def proposed_convention(revision: str) -> str | None:
    match = CONVENTION.search(revision)
    return None if not match or NONE.search(match[1]) else match[1].strip()
