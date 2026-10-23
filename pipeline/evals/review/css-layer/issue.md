# Selected text in user bubbles is invisible

## Problem
When you drag across a user message, the selection highlight is the same colour as the bubble (`--accent-soft`), so you cannot see what you selected.

## Proposed design
Give user bubbles a darker selection highlight (`--accent-line`) with white text. Leave the page-wide highlight as it is.

## Acceptance criteria
- Selecting text in a user bubble shows a visible `--accent-line` highlight with white text.
- Selection elsewhere on the page is unchanged.
