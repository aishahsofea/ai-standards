import re
from dataclasses import dataclass

ACTIONS = {
    "baseline": ("approve", "reject"),
    "gate-a": ("answer", "approve"),
    "plan": ("approve", "reject"),
    "gate-b": ("approve", "revise", "reject"),
    "allow": ("allow",),
}
STEP_NAMES = {
    "baseline": "baseline check", "gate-a": "open questions", "plan": "plan", "gate-b": "final review", "allow": "command permission",
}
MAX_NOTE_CHARS = 300
UNSAFE_LINE = re.compile(r"(?:/|>|Q\d+:)")


@dataclass(frozen=True)
class Answer:
    n: int
    text: str
    revisit: bool = False


@dataclass(frozen=True)
class Action:
    kind: str
    answers: tuple[Answer, ...] = ()
    rule: str = ""
    feedback: str = ""


def invalid_reason(key: str, action: Action) -> str | None:
    valid = ACTIONS[key]
    if action.kind in valid:
        return None
    options = " or ".join([", ".join(valid[:-1]), valid[-1]] if len(valid) > 1 else valid)
    return f"the {STEP_NAMES[key]} step only takes {options}"


def one_line(text: str) -> str:
    return " ".join(text.split())


def neutralize(feedback: str) -> str:
    """Indents lines that the pipeline would read as a command, an answer or a quote."""
    first, *rest = feedback.strip().splitlines() or [""]
    return "\n".join([first, *(f" {line}" if UNSAFE_LINE.match(line) else line for line in rest)])


def render_comment(action: Action, words: str = "") -> str:
    """The exact comment to post; the user's words only ever appear in a one-line quote."""
    match action.kind:
        case "answer":
            body = "\n".join(f"Q{a.n}: {'!' if a.revisit else ''}{one_line(a.text).removeprefix('!')}" for a in action.answers)
        case "revise":
            body = f"/revise {neutralize(action.feedback)}"
        case "allow":
            body = f"/allow {action.rule}"
        case kind:
            body = f"/{kind}"
    note = one_line(words)[:MAX_NOTE_CHARS]
    return f'{body}\n\n> via chat: "{note}"' if note else f"{body}\n\n> via chat: button"
