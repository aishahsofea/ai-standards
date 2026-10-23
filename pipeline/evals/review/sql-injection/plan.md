# Plan

## Phase 1: find_by_email
- Add `find_by_email(db, email)` to `app/users.py`, with tests.
- Verify: `pytest tests/test_users.py`

## Acceptance criteria
- Known email returns the user: Phase 1, `test_find_by_email_returns_the_matching_user`
- Unknown email returns None: Phase 1, `test_find_by_email_returns_none_when_missing`
