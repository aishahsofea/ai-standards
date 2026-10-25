from pipeline.validate import analysis_problems, decisions_problems, plan_problems, question_ids, reference_problems

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


def test_analysis_must_ask_about_the_interaction_pattern_of_ui_issues():
    open_ended = "Add a delete button to each sidebar row with a confirm step."
    asked = "## Open questions\n- **Q1:** Should the confirm step be a modal or inline?\n"
    assert analysis_problems(asked, open_ended) == []
    assert analysis_problems(ANALYSIS, open_ended) == [
        "the issue changes the UI without fixing the interaction pattern; raise an open question on it (modal vs inline, toast vs banner, placement)"
    ]
    assert analysis_problems(ANALYSIS, "Add a delete button that opens a confirm modal.") == []
    assert analysis_problems(ANALYSIS, "Add a CSV export endpoint.") == []


def test_valid_decisions_have_no_problems():
    assert decisions_problems(DECISIONS, ANALYSIS) == []


def test_decisions_need_every_section_and_question():
    broken = DECISIONS.replace("## Decided, low stakes\nNone.\n\n", "").replace("- **Q2: b**", "- **Q9: b**")
    assert decisions_problems(broken, ANALYSIS) == ["missing a '## Decided, low stakes' section", "no decision for Q2"]


def test_decisions_report_an_unreadable_escalated_section():
    unreadable = DECISIONS.replace("- **Q2: b**", "Q2: b")
    assert any("Escalated" in problem for problem in decisions_problems(unreadable, ANALYSIS))


PLAN = """# Plan

## Phase 1: icons
- Verify: `npx --prefix frontend vitest run Messages.test.tsx`

## Phase 2: selection
- Verify: `npx --prefix frontend playwright test selection.spec.ts`
- Manual checks: highlight colour looks right

## Acceptance criteria
- No visible Copy text: Phase 1, `Messages.test.tsx`
- Selection is visible and copies: Phase 2, `selection.spec.ts`
- Icons look polished: Manual: visual judgement

## Out of scope
- dark mode
"""


def test_valid_plan_has_no_problems():
    assert plan_problems(PLAN) == []
    assert plan_problems(PLAN.replace(PLAN[PLAN.index("- No visible"):PLAN.index("## Out")], "None.\n\n")) == []


def test_plan_needs_numbered_phases():
    assert plan_problems("no phases") == ["number the phases '## Phase 1', '## Phase 2', ... from 1 with no gaps"]


def test_plan_phases_need_an_automated_verify_line():
    plan = PLAN.replace("- Verify: `npx --prefix frontend vitest run Messages.test.tsx`", "- Change: x").replace(
        "selection.spec.ts`\n- Manual", "selection.spec.ts`, plus a manual browser check\n- Manual")
    assert plan_problems(plan) == [
        "phase 1 has no Verify: line",
        "phase 2's Verify: line has a manual step; move it to a 'Manual checks:' line",
    ]


def test_every_acceptance_criterion_needs_a_covering_phase():
    plan = PLAN.replace("copies: Phase 2,", "copies:").replace("text: Phase 1", "text: Phase 4")
    assert plan_problems(plan) == [
        "acceptance criterion names a phase that does not exist: No visible Copy text: Phase 4, `Messages.test.tsx`",
        "no phase covers acceptance criterion: Selection is visible and copies: `selection.spec.ts`",
    ]
    assert plan_problems(PLAN.replace("## Acceptance criteria", "## Criteria")) == [
        "missing a '## Acceptance criteria' section mapping each criterion to a phase"
    ]
