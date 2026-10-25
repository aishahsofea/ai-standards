---
name: analyze
description: Headless issue analysis for the pipeline. Reads an issue and the code it touches, then replies with a findings document whose open questions the decide stage answers.
---

# Analyze

Never ask questions. Your final reply is the findings document; do not write files or change code.

## Steps

1. Read the issue file named in the prompt: title, description, acceptance criteria, and constraints raised in comments.
2. Research the current code. Locate the files, modules and tests the issue touches, and read enough to know how they behave. Honor any `AGENTS.md`/`CONTEXT.md` in the repo, and `UX_CONVENTIONS.md` in the repo root if it exists. A UI question it already answers is not an open question.
3. Reply with these `##` sections, in order:
   - **Problem**: what the issue asks for, in your own words.
   - **Current state**: how the code works today.
   - **Proposed changes**: what changes and where.
   - **Effort**: S/M/L with a one-line reason.
   - **Risk**: what could break, blast radius, compatibility, test gaps.
   - **Open questions**: one `- **Q1:** ...` entry per question, numbered `Q1`, `Q2`, ... (or `None.`).

## Rules

- Cite code as `` `path/from/repo/root:line` ``; the pipeline rejects references to missing files or lines.
- Open questions are what the issue or code leaves ambiguous. Do not answer them; the decide stage does.
- If the issue changes the UI and its wording does not fix the interaction pattern (modal vs inline, toast vs banner, placement), raise an open question about it. Name the options.
- Do not write a plan.
