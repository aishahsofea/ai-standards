---
name: implement-phase
description: Implement exactly one phase of a plan test-first in a fresh context, then summarize it. Use when a plan file and a phase number are given, in a pipeline or when asked to build a single plan phase.
---

# Implement Phase

Build one phase of the plan and nothing else. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the phase summary.

## Steps

1. Read the plan, the earlier phase summaries, and any `AGENTS.md`/`CONTEXT.md`. Read the code the phase touches. The plan and summaries are your only memory of earlier work.
2. Build it with the [tdd](../tdd/SKILL.md) skill: one failing test, then the minimal code to pass it, repeated.
3. Run the phase's `Verify` step and the existing tests for the area. Match the surrounding code's style.
4. If verification fails twice, stop and report it. Do not keep retrying.

## Rules

- Implement only the named phase. Do not start later phases or clean up unrelated code.
- Do not commit, push, or open a PR; the pipeline does that.
- Report results honestly: failures and skipped checks go in the summary.

## Summary format

The first line is `Status: done` or `Status: blocked - <reason>`. Then:

- **Changed** — files with `file:line` and one line each.
- **Verified** — commands run and their outcome.
- **Deviations** — differences from the plan and why, or `None.`
- **Seams tested** — the public interfaces your tests cover.
