---
name: decide
description: Sort an analysis's open questions into decide-from-evidence, decide-and-record, and escalate-to-human, and write decisions.md. Use after issue analysis and before planning, in a pipeline or when asked to resolve open questions.
---

# Decide

Turn the open questions in an analysis into decisions, and escalate only what a human must answer.

## Inputs

The issue and its analysis (files named in the prompt). Read the code and any `AGENTS.md`/`CONTEXT.md` before deciding. Headless: never ask questions; your final reply is the `decisions.md` document.

## Sort each open question into one bucket

1. **Answerable from code or standards.** Decide it and cite the evidence (`file:line`, or the standard's name and section). Open the cited file; never cite from memory.
2. **Low-stakes and easy to reverse.** Decide it and say why it is cheap to undo (naming, internal structure, defaults, test layout).
3. **Escalate** if it touches product behavior, scope, a data model, a public API or interface, security, cost, or anything hard to reverse. Also escalate if you cannot ground the choice in evidence. When torn between 2 and 3, escalate.

Add questions the analysis missed if the code reveals them. Do not invent facts or evidence.

## Output format

Use exactly these headings so later stages can parse them:

```markdown
# Decisions

## Decided from evidence
- **Q1: <question>** — <decision>. Evidence: `<file:line>` or <standard>.

## Decided, low stakes
- **Q2: <question>** — <decision>. Why reversible: <one line>.

## Escalated
- **Q3: <question>** — Why a human must decide: <one line>. Options: <A, B>. Recommendation: <option and reason>.
  Answer: _pending_
```

Cover every `Q#` from the analysis. Cite evidence as `` `path/from/repo/root:line` ``; the pipeline rejects references to missing files or lines. Write `None.` under a heading with no entries. Never drop `## Escalated`: Gate A reads it, and the human writes their answer on each `Answer:` line.

## Excuses to reject

| Excuse | Reply |
|---|---|
| "It is only a small API detail." | Anything public or external is hard to reverse. Escalate. |
| "The human would probably pick my recommendation." | Probably is not evidence. Escalate. |
| "I'll decide it now and the plan can revisit it." | Later stages treat decisions as binding. Escalate. |
| "It sounds like a security question, but the fix is obvious." | Security and data-model choices always go to a human. |
| "I remember how the code works." | Open the file and cite `file:line`, or escalate. |

## Rules

- Decide as little as is safe: a wrongly decided hard-to-reverse question costs more than an extra escalation.
- One or two lines per entry. No restating the analysis.
- Never change code or write files other than via the final reply.
