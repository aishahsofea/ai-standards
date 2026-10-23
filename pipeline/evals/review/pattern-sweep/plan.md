# Plan

## Phase 1: Render comments and replies
- Add `render_comment` and `render_reply` to `web/render.py`, with tests.
- Verify: `pytest tests/test_comments.py -k render`

## Phase 2: Reply email
- Add `reply_email_html` in `web/notify.py`, with a test.
- Verify: `pytest tests/test_comments.py -k email`

## Acceptance criteria
- A comment shows its author and body: Phase 1, `test_render_comment_shows_author_and_body`
- A reply shows its author and body: Phase 1, `test_render_reply_shows_author_and_body`
- A reply sends an HTML email quoting the reply: Phase 2, `test_reply_email_quotes_the_reply`
