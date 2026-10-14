from pipeline.gates import confirm, escalated_section

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
