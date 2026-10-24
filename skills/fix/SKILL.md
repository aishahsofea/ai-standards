---
name: fix
description: Apply a failed review's Critical and Required findings test-first, then summarize the fixes. Use after a review fails, in a pipeline or when asked to address review findings on a feature branch.
---

# Fix

Fix what the review found and nothing else. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the fix summary.

## Steps

1. Read the issue, plan, test report, and failed review. Read the code each finding names.
2. For each Critical and Required finding, follow the [tdd](../tdd/SKILL.md) skill: write a test that fails because of the finding, then make the smallest change that passes it. Apply a Nit only if it is a one-line change in a file you are already fixing.
3. A finding that needs a browser or a person (an unrun manual check) is not code to change: list it under Manual checks.
4. The failed review may end with "Replies on the issue" from the owner. A finding or manual check a reply accepts or confirms is settled: list it under Not fixed citing the reply, tick its check, and do not report `blocked` for it.
5. Run the tests for every area you changed, each from the repo root as a single command: use `npm --prefix <dir> ...`, never `cd <dir> && ...` or `source`/`nvm`.
6. If a finding's fix fails verification twice, stop and report it. Do not keep retrying.

## Rules

- Fix only the review's findings. Do not refactor, add features, or start new plan work.
- Never weaken, skip, or delete a test to make it pass.
- If you think a finding is wrong, do not fix it: say why under Not fixed. The review reruns and decides.
- Do not commit, push, or open a PR; the pipeline does that.

## Excuses to reject

| Excuse | Reply |
|---|---|
| "The fix is obvious, so it needs no test." | The review found it because the tests missed it. Write the failing test first. |
| "While I'm here I'll clean this up." | Only the findings. List anything else under Not fixed. |
| "The finding is close enough to fixed." | Run the test. If it still fails, report `Status: blocked`. |

## Summary format

The first line must be exactly `Status: done` or `Status: blocked - <reason>`. Use `blocked` if a fix failed verification twice. Any other first line stops the run as blocked. Then:

- **Fixed** — each finding: its label, `file:line` of the change, and the test that now covers it.
- **Not fixed** — each finding left alone and why, or `None.`
- **Verified** — commands run and their outcome.
- **Manual checks** — the `- [ ]` checklist carried from the review. `None.` if empty.
