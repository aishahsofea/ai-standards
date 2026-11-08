---
name: ui-conventions
description: Pick a UI or interaction pattern (modal vs inline, toast vs banner, placement, navigation) when the request does not name one. Use when building, planning or changing UI, in a pipeline or interactively.
---

# UI Conventions

Settle a UI pattern from the first source that answers it, and cite that source:

1. `UX_CONVENTIONS.md` in the repo root, if it exists. Cite `UX_CONVENTIONS.md:<line>`.
2. The repo's existing pattern for the same kind of action, such as a modal used for another destructive action. Cite that component's `file:line`.
3. A widely established web convention, such as those below. Cite it by name.

If none answers it, the pattern is a product decision: do not guess.

## Widely established web conventions

- The logo or product name links to the home page.
- Escape closes a dialog, menu or drawer, and focus returns to the control that opened it.
- Clicking outside a menu or popover closes it.
- Links navigate; buttons act. Never make a clickable `div`.
- A destructive action asks for confirmation or offers undo.
- A submit button shows it is working and cannot be pressed twice.
- Form errors appear next to the field they belong to.
- Navigation marks the current page, and each page has its own title.
- Sign-out lives in the account menu.
- Below 768 px, top navigation collapses into a menu, and touch targets are at least 44×44 px.

A repo rule (source 1 or 2) overrides a web convention. A web convention restates nothing about this repo, so never propose it for `UX_CONVENTIONS.md`.
