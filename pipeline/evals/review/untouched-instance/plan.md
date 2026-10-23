# Plan

## Phase 1: Escape usernames in follow events
- Escape the username in `render_follow`, with a test.
- Verify: `pytest tests/test_feed.py`

## Acceptance criteria
- No username in the feed is rendered as HTML: Phase 1, `test_follow_escapes_the_username`
