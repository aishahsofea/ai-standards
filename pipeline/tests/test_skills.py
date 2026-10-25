from pipeline.cli import SKILLS_DIR


def test_test_and_review_skills_use_the_definition_of_done():
    default = (SKILLS_DIR / "DEFINITION_OF_DONE.md").read_text()
    assert len([line for line in default.splitlines() if line.startswith("- ")]) == 8
    for skill in ("test", "review"):
        text = (SKILLS_DIR / skill / "SKILL.md").read_text()
        assert "DEFINITION_OF_DONE.md" in text and "../DEFINITION_OF_DONE.md" in text


def test_stages_that_shape_ui_read_the_ux_conventions():
    for skill in ("analyze", "decide", "plan", "implement-phase", "review"):
        assert "`UX_CONVENTIONS.md`" in (SKILLS_DIR / skill / "SKILL.md").read_text()
