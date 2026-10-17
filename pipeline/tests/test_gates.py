from pipeline.gates import confirm, escalated_section, plan_preview

DECISIONS = """# Decisions

## Decided
- use sqlite

## Escalated
1. Public API shape?
2. Data model?

## Notes
later
"""


def test_escalated_section_stops_at_next_heading():
    section = escalated_section(DECISIONS)
    assert section.startswith("## Escalated")
    assert "Data model?" in section
    assert "Notes" not in section


def test_escalated_section_at_end_of_file():
    assert escalated_section("## Escalated\n1. q") == "## Escalated\n1. q"


def test_escalated_section_missing():
    assert escalated_section("## Decided\n- x") == ""


def test_confirm_accepts_only_yes():
    assert confirm("ok?", lambda _: " Y ")
    assert confirm("ok?", lambda _: "yes")
    assert not confirm("ok?", lambda _: "")
    assert not confirm("ok?", lambda _: "no")


PLAN = """# Plan: x

## Assumptions
- sqlite is fine

## Phase 1: Schema
- Verify: pytest

### Phase 2: API
- Verify: pytest

## Out of scope
- auth
"""


def test_plan_preview_lists_titles_assumptions_and_out_of_scope():
    preview = plan_preview(PLAN)
    assert "1. Schema" in preview and "2. API" in preview
    assert "## Assumptions\n- sqlite is fine" in preview
    assert "## Out of scope\n- auth" in preview
    assert "Verify" not in preview


def test_plan_preview_omits_missing_sections():
    assert "Assumptions" not in plan_preview("## Phase 1: A\n")


def test_escalated_section_hides_answered_entries():
    decisions = "## Escalated\n- **Q1: a** — x\n  Answer: sqlite\n- **Q2: b** — y\n  Answer: _pending_\n"
    section = escalated_section(decisions)
    assert "Q2" in section and "Q1" not in section


def test_escalated_section_when_all_answered():
    assert escalated_section("## Escalated\n- **Q1: a**\n  Answer: yes\n") == "## Escalated\nAll answered."
