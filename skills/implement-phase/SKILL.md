---
name: implement-phase
description: Implement exactly one phase of a plan test-first in a fresh context, then summarize it. Use when a plan file and a phase number are given, in a pipeline or when asked to build a single plan phase.
---

# Implement Phase

Build one phase of the plan and nothing else. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the phase summary.

## Steps

1. Read the plan, the earlier phase summaries, and any `AGENTS.md`/`CONTEXT.md`. Read the code the phase touches. The plan and summaries are your only memory of earlier work.
2. Build it with the [tdd](../tdd/SKILL.md) skill: one failing test, then the minimal code to pass it, repeated.
3. Run the phase's `Verify` step and the existing tests for the area. Run each command from the repo root as a single command: use `npm --prefix <dir> test` or `npx --prefix <dir> vitest run <path>`, never `cd <dir> && ...` or `source`/`nvm`. Match the surrounding code's style.
4. You have no browser or GUI. If the phase lists a manual or browser check, or a change conditional on one, do not block on it: apply the plan's safe default, then list the check under Deviations as `Manual check (not run)`. Report `Status: done` when every command-runnable `Verify` step passes. Do not carry earlier phases' manual checks forward, and leave PR, issue and other GitHub actions to the pipeline.
5. If verification fails twice, stop and report it. Do not keep retrying.

## Excuses to reject

| Excuse | Reply |
|---|---|
| "The change is too small to need a test." | Write the failing test first. Small changes break things too. |
| "I'll relax this assertion so the test passes." | The test is the spec. Fix the code, or report `Status: blocked`. |
| "That failure was already there." | Stash your change and rerun. If it still fails, list it under Deviations. If it passes, your change broke it. |
| "The next phase will cover it." | Only this phase counts. List missing work under Deviations in the summary. |
| "The probe needs a browser, so I'll block." | Apply the safe default, list it as a manual check, and report `Status: done`. |
| "Verification failed twice but it is close." | Stop. Report `Status: blocked` with the output. |

## Rules

- Implement only the named phase. Do not start later phases or clean up unrelated code.
- Do not commit, push, or open a PR; the pipeline does that.
- Report results honestly: failures and skipped checks go in the summary.

## Summary format

The first line must be exactly `Status: done` or `Status: blocked - <reason>`. Any other first line stops the run as blocked. Then:

- **Changed** — files with `file:line` and one line each.
- **Verified** — commands run and their outcome.
- **Deviations** — differences from the plan and why, or `None.`
- **Seams tested** — the public interfaces your tests cover.
