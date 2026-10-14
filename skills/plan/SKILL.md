---
name: plan
description: Turn an analyzed issue and its decisions into a phased implementation plan that one fresh run can execute per phase. Use after decisions are settled and before implementation, in a pipeline or when asked for a phased plan.
---

# Plan

Write a phased implementation plan from the issue, its analysis, and `decisions.md`. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the `plan.md` document. Do not change code.

## Inputs

The issue, analysis, and decisions files named in the prompt. Read the code the work touches and any `AGENTS.md`/`CONTEXT.md` first.

- Every decided and escalated answer in `decisions.md` is binding.
- If an escalated entry still says `_pending_`, use its recommendation and list it under `## Assumptions`.

## Phases

- Each phase is one small, independently reviewable diff with one concern. Prefer more, smaller phases. Optimize for review effort, not phase count.
- Each phase runs in a fresh context that sees only this plan and earlier phase summaries, so the plan must stand alone.
- Order phases so tests pass after each one. Defer unrelated cleanup.

## Output format

Use exactly `## Phase N: <title>` headings, numbered from 1 with no gaps: the pipeline counts them.

```markdown
# Plan: <feature>

## Assumptions
<only if any; otherwise omit>

## Phase 1: <title>
- Goal: <one line>
- Files: <paths>
- Change: <what changes and why>
- Verify: <exact test or command>
```

End with `## Out of scope` listing what the plan deliberately skips.
