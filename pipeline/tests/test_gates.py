import pytest

from pipeline.gates import GATE_A, GateError, answer_escalated, confirm, decisions_preview, escalated_entries, escalated_section, plan_preview

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


def test_answer_escalated_writes_typed_and_recommended_answers_and_skips_blank():
    decisions = (
        "## Escalated\n"
        "- **Q1: a?** Recommendation: A, simplest.\n  Answer: _pending_\n"
        "- **Q2: b?** Recommendation: B.\n  Answer: _pending_\n"
        "- **Q3: c?**\n  Answer: _pending_\n"
    )
    replies = iter(["r", "use Postgres", ""])
    updated = answer_escalated(decisions, lambda _: next(replies))
    assert "Answer: A, simplest." in updated
    assert "Answer: use Postgres" in updated
    assert "Q3: c?**\n  Answer: _pending_" in updated


def test_answer_escalated_adds_missing_answer_line():
    assert answer_escalated("## Escalated\n1. Pick?\n", lambda _: "sqlite").strip().endswith("Answer: sqlite")


def test_decisions_preview_lists_decided_items_before_escalations():
    decisions = "## Decided from evidence\n- **Q1: a** — x\n## Decided, low stakes\n- **Q2: b** — y\n## Escalated\n- **Q3: c**\n  Answer: _pending_\n"
    preview = decisions_preview(decisions)
    assert preview.index("Q1") < preview.index("Q2") < preview.index("Q3")


@pytest.mark.parametrize("entry", ["1) Pick?", "### Escalated\n", "**Q1: Pick?**"])
def test_escalated_entries_accept_format_variants(entry):
    text = f"## Escalated\n{entry}" if "Escalated" not in entry else f"## Decided\n- x\n{entry}1. Pick?\n"
    assert len(escalated_entries(text)) == 1


@pytest.mark.parametrize("decisions", ["## Decided\n- x\n", "## Escalated\nsome prose, no list\n"])
def test_escalated_entries_fail_loudly_when_unreadable(decisions):
    with pytest.raises(GateError):
        escalated_entries(decisions)


def test_escalated_none_means_no_entries():
    assert escalated_entries("## Escalated\nNone.\n") == []


def test_answer_escalated_multi_line_reply_reads_until_blank_line():
    replies = iter(["m", "use Postgres", "and keep a rollback", ""])
    updated = answer_escalated("## Escalated\n- **Q1: a?**\n  Answer: _pending_\n", lambda _: next(replies))
    assert "Answer: use Postgres\n    and keep a rollback" in updated
    assert not escalated_entries(updated)


def test_answer_escalated_bang_marks_the_answer_for_revisit():
    updated = answer_escalated("## Escalated\n- **Q1: a?**\n  Answer: _pending_\n", lambda _: "!use Postgres")
    assert "Answer: [revisit] use Postgres" in updated
    assert GATE_A.needs_rerun(updated)
    assert not GATE_A.needs_rerun(updated.replace("[revisit] ", ""))
