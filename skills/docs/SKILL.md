---
name: docs
description: Update a feature's documentation in plain English and write the PR description that explains what changed and why, phase by phase. Use after implementation and testing, in a pipeline or when asked for docs and PR text.
---

# Docs

Update the docs the feature affects and write the PR text. Headless (the prompt says to run non-interactively): never ask questions; your final reply is the PR description.

## Steps

1. Read the plan, phase summaries, test report, and review. Check the diff against the base branch for what actually changed.
2. Update existing docs the change makes wrong or incomplete (README, usage, config). Add new docs only where the feature needs them.
3. Follow the [plain-english](../plain-english/SKILL.md) skill on every doc you wrote or changed.
4. Do not commit or push; the pipeline does that.

## PR description format

The reader is a reviewer who did not watch the work and may not know the feature well.

- **Summary** — what the feature does and why, in two or three sentences.
- **By phase** — for each plan phase: what changed and why it was done that way.
- **Decisions** — decisions that shaped the design, including the human-answered ones.
- **Verification** — test report result, any acceptance criteria not covered, and every open Required or Nit finding from the review.
- **Manual checks** — the review's `- [ ]` checklist, copied as is, for a person to tick before merge.
- **Docs updated** — files changed.

State failures, open concerns, and deviations from the plan plainly.
