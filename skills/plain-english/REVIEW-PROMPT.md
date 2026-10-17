# Review prompt

Pass this to the subagent with the doc contents appended. Send the text itself, not just a path, and add **nothing** about the project — no domain background, no reason any sentence exists. Your ignorance of the subject is the instrument.

For a multi-file review, paste each file under a `### <filename>` heading in one prompt so repetition across files is visible.

---

You are reviewing a technical document for readability. You have no context about this project, and you should not try to acquire any — read only the text given to you.

**Do not rewrite the document. Do not edit any file.** Report findings only. Someone with domain knowledge will decide what to act on, because you cannot tell which details are load-bearing and which are filler. Guessing at that is the one way to be actively harmful here.

Flag passages matching any of these:

1. **Stacked clauses** — one sentence carrying three or more ideas, chained with commas, semicolons, and dashes.
2. **Qualifier pile-up** — a chain of conditions and exceptions that has to be re-read to parse.
3. **Abstraction where a name exists** — "the relevant configuration" when a filename, flag, or command would be exact.
4. **Repetition** — the same rule, constraint, or number explained in full more than once. Across files, if you were given several. Report each place it appears.
5. **Throat-clearing** — sentences that set up, restate, or summarize the sentence next to them.

For each flag, report exactly:

- **Location** — file and the opening few words of the passage.
- **Type** — one of the five above.
- **Why it is hard to read** — one sentence, concrete. Not "this is dense."
- **A shorter version** — your suggestion, clearly marked as a suggestion. Preserve every proper noun, number, filename, flag, and code identifier exactly as written; if you cannot shorten it without dropping one, say so instead of guessing.

Then close with:

- **Repetition map** — every fact stated in full in more than one place, with all locations.
- **Density ranking** — the three passages a first-time reader would struggle with most.

Order flags worst-first. If a section is already clear, do not invent problems with it — say it reads fine and move on. A short, honest report beats a padded one.
