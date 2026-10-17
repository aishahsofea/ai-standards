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
4. Map each acceptance criterion in the issue to the test or command that covers it. Mark uncovered criteria as `Not covered`.

## Rules

- Never weaken, skip, or delete a test to make it pass.
- Do not commit, push, or add features.
- Report honestly: failures, skipped checks, and anything you could not run.

## Report format

The first line is `Status: pass` or `Status: fail`. Then:

- **Commands** — each command with pass or fail.
- **Acceptance criteria** — each criterion with its covering test, or `Not covered`.
- **Failures** — the relevant output excerpt for each remaining failure, or `None.`
- **Fixes made** — what you changed during this stage, or `None.`
