---
name: plain-english
description: Review docs for dense, over-qualified "AI voice" prose using a fresh-context subagent that flags passages instead of rewriting them, then verify a rewrite actually cut length without dropping facts. Use when writing or reviewing docs (README, CONTRIBUTING, architecture notes, ADRs), when prose reads dense or jargon-stacked, when the user says "claudish", "sounds like AI wrote it", or "make this readable", and after any doc rewrite to check it was a real cut and not a reword.
---

# Plain English

Dense docs come from writing with full context loaded. Every qualifier feels load-bearing when you remember why you put it there. You cannot catch this in your own prose — you know too much about it. This skill borrows a reader who knows nothing.

## Why a subagent, not a checklist

A style rule in `CLAUDE.md` instructs the same model that produced the density. Self-review fails: it is easy to split a sentence, declare it plain English, and change nothing. What works is a second reader with **no memory of why the text says what it says**.

That same ignorance cuts both ways. A fresh reader spots density but cannot tell a load-bearing invariant from filler. So:

> **The subagent flags. You decide. Never let it rewrite the file.**

## Reviewing a doc

Spawn a subagent (`Agent`, `subagent_type: general-purpose`) with the doc contents and the prompt in [REVIEW-PROMPT.md](REVIEW-PROMPT.md). Give it **no domain context** and no explanation of why anything is there — that is the whole point.

Headless (the prompt says to run non-interactively): never ask questions, and apply the cuts you keep. With no subagent tool, review the text yourself against the five flag types in the review prompt.

Then triage every flag yourself:

- **Filler** — hedges, restated clauses, abstractions with a concrete name available → cut.
- **Load-bearing** — an invariant, a safety rule, an exact constraint someone acts on → keep the fact, shorten the sentence around it.

Precision beats brevity when they conflict. Shorten the prose; never cut the fact.

## Verifying a rewrite

Three checks. A rewrite that passes none of them is a reword.

**1. Word count.** Restructuring prose moves it a few percent. Cutting duplication moves it 20%+.

```bash
git show HEAD:path/to/doc.md | wc -w && wc -w path/to/doc.md
```

**2. Dropped facts.** Read the real diff, not your summary of it. Removing a duplicate is the goal; removing the only copy of an endpoint, env var, or safety rule is a regression that is easy to miss and easy to ship.

```bash
git diff path/to/doc.md
```

**3. One fact, one home.** Across a doc set, each flag/constraint/number appears in full in exactly one file. Others describe it in a sentence and link. This is where real length comes off — not from rewording.

## Reword vs rewrite

The failure mode this skill exists to catch. Both "simplify" the same sentence; only one is worth committing.

| | |
|---|---|
| **Original** | An Act that has been amended and the latest version is maintained on the LOM portal. Identified by a numeric Act number. |
| **Reword** (worthless) | An Act that has been amended, with the latest version maintained on the LOM portal. Has a numeric Act number. |
| **Rewrite** (real) | An amended Act. The portal keeps its latest version. Identified by Act number. |

The reword swaps connectives and moves the word count ~4%. Nothing was made easier to read. Real cuts come from **removing repetition across the doc set**, then shortening what is left.

## Scope

Living docs and frozen records both. A frozen decision record (ADR, PRD) must not have its decision or reasoning changed to match later reality — but its prose can and should be readable. Rewrite the sentences, preserve every recorded fact.
