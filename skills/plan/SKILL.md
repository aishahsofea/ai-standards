---
name: plan
description: Turn an analyzed issue and its decisions into a phased implementation plan that one fresh run can execute per phase. Use after decisions are settled and before implementation, in a pipeline or when asked for a phased plan.
---

# Plan

Write a phased implementation plan from the issue, its analysis, and `decisions.md`. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the `plan.md` document. Do not change code.

## Inputs

The issue, analysis, and decisions files named in the prompt. Read the code the work touches and any `AGENTS.md`/`CONTEXT.md` first. Where the decisions do not fix a UI pattern, follow the [ui-conventions](../ui-conventions/SKILL.md) skill.

- Every decided and escalated answer in `decisions.md` is binding.
- If an escalated entry still says `_pending_`, use its recommendation and list it under `## Assumptions`.

## Phases

- Each phase is one small, independently reviewable diff with one concern. Prefer more, smaller phases. Optimize for review effort, not phase count.
- Each phase runs in a fresh context that sees only this plan and earlier phase summaries, so the plan must stand alone.
- Order phases so tests pass after each one. Defer unrelated cleanup.
- No phase may wait for the owner mid-run. Anything only the owner can supply (a captured fixture, a login, a secret, access to a deployed service) goes under `## Prerequisites`, naming the phase that needs it. The owner sees that list before any code is written.

## Verify and acceptance criteria

- `Verify` lists only commands a headless agent runs from the repo root, one at a time: `npm --prefix <dir> test`, `npx --prefix <dir> playwright test <spec>`. Never `cd`, `source` or `nvm`; the pipeline sets up Node.
- Every acceptance criterion in the issue gets an automated test in the phase that delivers it. The test asserts what the user gets, not how the code is written: a class name or attribute check does not cover "the highlight is visible".
- If the repo has Playwright (`@playwright/test` in the manifest), a criterion a browser can check (layout, scrolling, selection, copy, pointer, drag, keyboard, state after reload, viewport widths) gets a Playwright spec that asserts computed results (`getComputedStyle`, `getSelection()`, clipboard, bounding boxes). Name the spec in that phase's `Verify`.
- Only what a person must judge (visual polish, feel) is manual. Put it on a separate `Manual checks:` line, never in `Verify`. A check Playwright could run is never manual in a repo with Playwright.

## Output format

Use exactly `## Phase N: <title>` headings, numbered from 1 with no gaps: the pipeline counts them.

```markdown
# Plan: <feature>

## Prerequisites
<only if any; otherwise omit>
- Phase N: <what the owner must supply, and where to put it>

## Assumptions
<only if any; otherwise omit>

## Phase 1: <title>
- Goal: <one line>
- Files: <paths>
- Change: <what changes and why>
- Verify: <exact commands>
- Manual checks: <only if any; otherwise omit>

## Acceptance criteria
- <criterion from the issue>: Phase N, `<test or spec that covers it>`
- <criterion only a person can judge>: Manual: <why>
```

The pipeline rejects the plan if a phase has no `Verify:` line, a `Verify:` line mentions a manual step, or an acceptance criterion names no existing `Phase N` and is not marked `Manual:`. Write `None.` under `## Acceptance criteria` only if the issue has none.

End with `## Out of scope` listing what the plan deliberately skips.
