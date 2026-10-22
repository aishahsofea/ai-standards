from pipeline.validate import analysis_problems, decisions_problems, question_ids, reference_problems

ANALYSIS = "# Analysis\n\n## Current state\nSee `src/app.py:2`.\n\n## Open questions\n- **Q1:** a?\n- **Q2:** b?\n"
DECISIONS = """# Decisions

## Decided from evidence
- **Q1: a** — yes. Evidence: `src/app.py:2`.

## Decided, low stakes
None.

## Escalated
- **Q2: b** — Why a human must decide: api. Options: x, y. Recommendation: x.
  Answer: _pending_
"""


def test_question_ids_read_bullets_bold_and_numbering():
    text = "- **Q1:** a\n2. **Q2** b\nQ3. c\n  * Q4: d\nsee Q5 here\n- **Q1:** again\n"
    assert question_ids(text) == ["Q1", "Q2", "Q3", "Q4"]


def test_reference_problems_flag_missing_files_and_lines(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("a\nb\nc\n")
    text = "`src/app.py:3` `src/app.py:2-3` `src/app.py:9` `src/gone.py:1` `localhost:8080`"
    assert reference_problems(text, tmp_path) == ["`src/app.py:9` is past the end of the file", "`src/gone.py` does not exist"]


def test_analysis_needs_numbered_open_questions():
    assert analysis_problems(ANALYSIS) == []
    assert analysis_problems("# Analysis\n## Open questions\nNone.\n") == []
    assert analysis_problems("# Analysis\nno questions section") == ["missing a '## Open questions' section"]
    assert analysis_problems("## Open questions\n- what about x?\n") == [
        "number each open question Q1, Q2, ... or write 'None.' under '## Open questions'"
    ]


def test_valid_decisions_have_no_problems():
    assert decisions_problems(DECISIONS, ANALYSIS) == []


def test_decisions_need_every_section_and_question():
    broken = DECISIONS.replace("## Decided, low stakes\nNone.\n\n", "").replace("- **Q2: b**", "- **Q9: b**")
    assert decisions_problems(broken, ANALYSIS) == ["missing a '## Decided, low stakes' section", "no decision for Q2"]


def test_decisions_report_an_unreadable_escalated_section():
    unreadable = DECISIONS.replace("- **Q2: b**", "Q2: b")
    assert any("Escalated" in problem for problem in decisions_problems(unreadable, ANALYSIS))
