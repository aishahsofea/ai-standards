# Plan

## Phase 1: Loading state on the submit button
- Add a `loading` flag to `render_submit` and an `.is-loading` style, with tests.
- Verify: `pytest tests/test_forms.py`

## Acceptance criteria
- Cannot be clicked or submitted while loading: Phase 1, `test_submit_shows_loading_state`
- Looks busy while loading: Phase 1, `test_submit_shows_loading_state`
