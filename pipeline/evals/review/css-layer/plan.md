# Plan

## Phase 1: Bubble selection highlight
- Add a `.bubble-select` selection rule in the `utilities` layer of `static/app.css` and put the class on user bubbles in `web/message.py`, with a test.
- Verify: `pytest tests/test_message.py`

## Acceptance criteria
- User bubble selection uses `--accent-line`: Phase 1, `test_user_message_uses_the_bubble_selection_highlight`
- Selection elsewhere unchanged: Phase 1, the global `::selection` rule is not edited
