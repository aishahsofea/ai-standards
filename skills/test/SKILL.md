---
name: test
description: Run a feature's full test, lint, and build checks, fix small breakages, and report against the issue's acceptance criteria. Stops after two failing runs. Use after all plan phases are implemented, in a pipeline or when asked to test a finished feature.
---

# Test

Verify the finished feature end to end. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the test report.

## Steps

1. Find the repo's check commands (`AGENTS.md`, `CONTEXT.md`, the manifest, CI config). Run tests, lint, and build.
2. If something fails, fix the cause only when it is small and clearly a bug in this feature's changes, then rerun.
3. **Stop after two failing runs.** Do not fix further; report what still fails.
4. Check the feature against the definition of done: `DEFINITION_OF_DONE.md` in the repo root if it exists, else [the built-in default](../DEFINITION_OF_DONE.md). Fix an unmet item only if it is small and in this feature's changes.
5. Map each acceptance criterion in the issue to the test or command that covers it. Mark uncovered criteria as `Not covered`.

## Rules

- Never weaken, skip, or delete a test to make it pass.
- Do not commit, push, or add features.
- Report honestly: failures, skipped checks, and anything you could not run.

## Excuses to reject

| Excuse | Reply |
|---|---|
| "This test is flaky, so skip it." | Rerun it once. If it fails again, it is a failure. Report it. |
| "That failure is unrelated to the feature." | Rerun on the base branch. If it passes there, your change broke it. |
| "I'll loosen the assertion." | Never. Fix the cause or report `Status: fail`. |
| "The lint warning is only style." | A failing lint command is a failing check. |
| "I could not run it, but the code looks right." | List it as not run. It is not a pass. |

## Report format

The first line must be exactly `Status: pass` or `Status: fail`. Any other first line stops the run as blocked. Then:

- **Commands** — each command with pass or fail.
- **Acceptance criteria** — each criterion with its covering test, or `Not covered`.
- **Definition of done** — each item met, or `Not met` with the reason.
- **Failures** — the relevant output excerpt for each remaining failure, or `None.`
- **Fixes made** — what you changed during this stage, or `None.`
