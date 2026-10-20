---
name: analyze-issue
description: Fetch an issue/work-item from a GitLab or GitHub link, research the codebase, and deliver a findings summary (changes, effort, risk) before producing a gated, phase-by-phase implementation plan. Use when given an issue/work-item/MR/PR link (gitlab.com or github.com) and asked to analyze it, scope the work, estimate effort/risk, or build a reviewable phased implementation plan.
---

# Analyze Issue → Findings → Phased Implementation

A two-stage workflow for open-source contribution. In interactive mode **never
skip a gate**: the human reviews and approves between stages and between every
implementation phase.

## Mode

- **Interactive** (default): follow every stage and gate below.
- **Headless** (the prompt says to run non-interactively): do Stage 1 only, with no
  gates. Read the issue from the input file or link given in the prompt, never ask
  questions, and make your final reply the findings document. Number each open
  question `Q1`, `Q2`, ... so a later stage can answer them. Do not write a plan,
  write files, or change code.

## Stage 1 — Analyze & report findings

1. **Fetch the issue.** Detect the host from the URL:
   - `gitlab.com/.../-/work_items/<n>` or `/-/issues/<n>` → `glab` (see [FETCHING.md](FETCHING.md))
   - `github.com/.../issues/<n>` or `/pull/<n>` → `gh` (see [FETCHING.md](FETCHING.md))
   - Read the title, description, labels, discussion/comments, and any linked
     issues/MRs/PRs. Note acceptance criteria and constraints raised in threads.
2. **Research the current code.** Locate the files, modules, and tests the issue
   touches. Read enough to understand actual behavior — do not guess. Honor any
   `AGENTS.md`/`AGENTS.md`/`CONTEXT.md` in the repo.
3. **Report findings** (interactive: chat only, no files written; headless: the final reply). Use this structure:
   - **Problem** — what the issue asks for, in your own words.
   - **Current state** — how the relevant code works today, with `file:line` refs.
   - **Proposed changes** — what needs to change and where.
   - **Effort** — rough size (S/M/L) with a one-line justification.
   - **Risk** — what could break, blast radius, migration/compat concerns, test gaps.
   - **Open questions** — anything ambiguous in the issue or code.
4. **Stop and wait** (interactive only). Ask the human to confirm or correct the findings. Do **not**
   write a plan or any code yet.

## Stage 2 — Phased implementation plan (only after findings are approved)

1. Break the work into **small, independently-reviewable phases**. Optimize for
   *human review effort*, not for the fewest phases. A phase should be a coherent,
   self-contained diff a reviewer can hold in their head — typically one concern
   (e.g. "add the config field", "wire it through", "add tests"). Prefer more,
   smaller phases over fewer large ones.
2. For each phase list: **goal**, **files touched**, **what changes**, and **how
   it's verified** (test/command). Keep the diff tight; defer unrelated cleanup.
   A phase's `Verify` must be a command a headless agent can run. Put checks that need a
   browser or a person under a separate `Manual checks` list for the PR, never as a phase's
   `Verify`, and never make a code change conditional on one. Pick the safe default.
3. Present the full phase list and **stop for approval** before implementing.

## Implementation loop (per phase)

For each approved phase, repeat:

1. Implement **only** that phase. No scope creep into later phases.
2. Verify it: run the repo's tests/lint/build for the touched area. Report results
   honestly — if something fails or was skipped, say so.
3. **Pause.** Summarize what changed (`file:line`) and the verification outcome,
   then ask for the go-ahead before starting the next phase.

## Rules

- Interactive: one gate per stage transition and one gate per phase. When in doubt, stop and ask.
- Findings and the plan stay in chat — do not write plan files unless asked.
- Match the surrounding code's style and the repo's contribution conventions.
- Don't open MRs/PRs, push, or commit unless explicitly told to.
