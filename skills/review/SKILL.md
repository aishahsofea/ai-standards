---
name: review
description: Read-only review of a finished feature's diff against the base branch on five axes (correctness, readability, architecture, security, performance), with findings labelled Critical, Required or Nit. Use after tests pass, in a pipeline or when asked to review a feature branch.
---

# Review

Review the finished feature as an independent reviewer. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the review. You are read-only: do not edit, create, commit, or push anything.

## Steps

1. Read the issue, plan, phase summaries, and test report from the input files.
2. Diff the branch against the base branch (`git diff <base>...HEAD`). Read the changed tests first: do they check behavior, and would they fail if the code broke? Then read the changed code in full.
3. Check each axis:
   - **Correctness**: matches the issue and plan; edge cases, error paths, state and race bugs.
   - **Readability**: names and structure match the surrounding code; no clever tricks or dead code.
   - **Architecture**: follows existing patterns; reuses the existing helper instead of a near-duplicate; keeps feature logic out of shared modules; reduces complexity rather than moving it.
   - **Security**: input and external data validated at boundaries; authorization checked; no injection or XSS; no secrets. New or upgraded dependencies: needed, maintained, lockfile diff matches.
   - **Performance**: no N+1 queries, unbounded loops or fetches, or needless re-renders.
4. Check the diff against the definition of done: `DEFINITION_OF_DONE.md` in the repo root if it exists, else [the built-in default](../DEFINITION_OF_DONE.md). Each unmet item is a Required finding.
5. Label every finding `Critical` (breaks behavior or is unsafe), `Required` (must change before merge), or `Nit` (optional). Give `file:line` and the fix for each.

## Rules

- Review the diff, not unrelated code.
- When a finding comes from a pattern (a cascade rule, a missing guard), search the diff and the files it touches for other instances and list each one.
- Do not soften a finding because the tests pass.
- Report honestly: say what you could not check.
- A criterion listed under the test report's Manual checks is not a finding: carry it to your Manual checks list. Flag it as Required only if Playwright could have checked it and the repo has Playwright.

## Excuses to reject

| Excuse | Reply |
|---|---|
| "The tests pass, so it is correct." | Tests cover only what they test. Check the diff. |
| "The author clearly meant well." | Review what the code does, not what was meant. |
| "This is a Nit really." | If it breaks behavior or is unsafe, it is Critical or Required. |
| "The diff is big, so I'll skim." | Read every changed file, or say what you skipped. |
| "I can fix it faster than I can describe it." | You are read-only. Describe the fix. |

## Report format

The first line must be exactly `Status: pass` or `Status: fail`. Use `fail` if any finding is Critical or Required. Any other first line stops the run as blocked. Then:

- **Findings** — Critical first, then Required, then Nit; one line each: label, `file:line`, problem, fix. `None.` if clean.
- **Axes** — one line per axis: what you checked.
- **Manual checks** — the `- [ ]` checklist for the PR, from the test report plus any you add. `None.` if empty.
