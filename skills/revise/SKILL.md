---
name: revise
description: Apply the owner's feedback on a finished feature (UI, UX or behavior they dislike) test-first, then summarize. Use after a pipeline run when the owner wants something changed before merging.
---

# Revise

Change the finished feature as the owner asked and nothing else. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the revision summary.

## Steps

1. Read the issue, plan, test report, review, PR text, and any earlier revisions. Read the code the feedback concerns.
2. Turn the feedback into acceptance criteria a test can check. When the feedback is about how the UI looks or behaves, follow the pattern the owner names (for example a modal instead of inline text) and assert the computed result, not class names.
3. Follow the [tdd](../tdd/SKILL.md) skill: write a test that fails against the current code, then make the smallest change that passes it. Where the repo has Playwright (`@playwright/test` in the manifest), a browser-checkable criterion gets a Playwright spec.
4. Update or remove an existing test only when the feedback reverses the behavior it checks, and say so under Changed tests.
5. Run the tests for every area you changed, each from the repo root as a single command: use `npm --prefix <dir> ...`, never `cd <dir> && ...` or `source`/`nvm`.
6. If the change fails verification twice, stop and report it. Do not keep retrying.

## Rules

- Apply only the feedback. Do not refactor, add features, or reopen earlier decisions.
- Never weaken, skip, or delete a test to make it pass.
- If the feedback conflicts with an acceptance criterion in the issue, apply the feedback and list the criterion under Superseded.
- If the feedback is too vague to act on, report `Status: blocked` and say what is missing.
- Do not commit, push, or open a PR; the pipeline does that.

## Excuses to reject

| Excuse | Reply |
|---|---|
| "The old behavior matched the issue, so it's fine." | The owner has now said what they want. Apply the feedback. |
| "While I'm here I'll tidy the neighbouring component." | Only the feedback. Mention anything else under Noticed. |
| "A class-name check shows the new UI is there." | Assert what the user sees and can do. |

## Summary format

The first line must be exactly `Status: done` or `Status: blocked - <reason>`. Any other first line stops the run as blocked. Then:

- **Feedback** — the owner's feedback, quoted verbatim.
- **Changed** — each change with `file:line`.
- **Acceptance criteria** — a bulleted list of the new criteria, each with the test that covers it.
- **Changed tests** — existing tests you edited and why, or `None.`
- **Superseded** — issue criteria the feedback replaced, or `None.`
- **Verified** — commands run and their outcome.
- **Manual checks** — what only a person can judge, as `- [ ]` items, or `None.`
- **Proposed convention** — one imperative line (for example "Destructive actions confirm in a modal, never inline.") when the feedback is a general rule for this repo's UI, else `None.`. A one-off preference for this feature is `None.`.
