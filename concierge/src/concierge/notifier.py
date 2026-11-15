import re
from dataclasses import dataclass, field

from concierge.requests import Comment, Request, allow_rules, artifact_text, open_questions
from pipeline.gates import PHASE_HEADING, commands_notice, section

MAX_TEXT_CHARS = 3_500
PART_CHARS = 1_500


@dataclass(frozen=True)
class Choice:
    label: str
    data: str


@dataclass(frozen=True)
class Prompt:
    text: str
    choices: tuple[Choice, ...]
    rules: list[str] = field(default_factory=list)


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plan_summary(plan: str) -> str:
    """The commands the plan would allow come first and are never cut; the other sections are."""
    titles = [f"{n}. {title.strip()}" for n, (_, title) in enumerate(PHASE_HEADING.findall(plan), 1)]
    sections = (("Prerequisites", 600), ("Assumptions", 400), ("Out of scope", 300))
    parts = (commands_notice(plan), "\n".join(["Phases:", *titles]), *(clip(section(plan, name), limit) for name, limit in sections))
    return "\n\n".join(part for part in parts if part)


def gate_a_summary(comments: list[Comment]) -> str:
    questions = open_questions(comments)
    lines = [f"Q{n}: {clip(entry, 400)}" for n, entry in questions.items()]
    return "\n\n".join(["Open questions:", *lines, "Reply with your answers, or accept every recommendation."]) if lines else ""


def summary(request: Request, comments: list[Comment]) -> str:
    match request.key:
        case "plan" if plan := artifact_text(comments, "plan"):
            return plan_summary(plan)
        case "gate-a" if text := gate_a_summary(comments):
            return text
        case "gate-b":
            pr = clip(artifact_text(comments, "pr") or "", PART_CHARS)
            head = re.search(r"Head commit: `[0-9a-f]+`", request.text)
            return "\n\n".join(part for part in (pr, head[0] if head else "") if part)
        case "allow":
            return "\n".join(["The agent was denied these commands:", *(f"- `/allow {rule}`" for rule in allow_rules(request))])
    return clip(request.text, PART_CHARS)


def choices(request: Request) -> tuple[Choice, ...]:
    match request.key:
        case "baseline":
            return Choice("Approve", "approve"), Choice("Reject", "reject")
        case "gate-a":
            return (Choice("Accept every recommendation", "approve"),)
        case "plan":
            return Choice("Approve plan", "approve"), Choice("Reject", "reject")
        case "gate-b":
            return Choice("Approve", "approve"), Choice("Revise", "revise"), Choice("Reject", "reject")
        case _:
            return tuple(Choice(f"Allow {rule}", f"allow:{i}") for i, rule in enumerate(allow_rules(request)))


def build_prompt(request: Request, comments: list[Comment]) -> Prompt:
    text = f"{clip(summary(request, comments), MAX_TEXT_CHARS)}\n\n{request.url}"
    return Prompt(text, choices(request), allow_rules(request) if request.key == "allow" else [])
