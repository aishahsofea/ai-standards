import re
from pathlib import Path

from pipeline.gates import GateError, escalated_entries, section

QUESTION = re.compile(r"(?m)^[\s\-*\d.)]*\**(Q\d+)\b")
REFERENCE = re.compile(r"`([\w@+-]*[./][\w@./+-]*):(\d+)(?:-(\d+))?`")
NONE = re.compile(r"(?mi)^\W*None\.?\s*$")


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


def analysis_problems(analysis: str) -> list[str]:
    questions = section(analysis, "Open questions")
    if not questions:
        return ["missing a '## Open questions' section"]
    if not question_ids(questions) and not NONE.search(questions):
        return ["number each open question Q1, Q2, ... or write 'None.' under '## Open questions'"]
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
