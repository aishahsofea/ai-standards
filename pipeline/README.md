# Feature pipeline

Takes a feature idea and produces a draft pull request. A fresh agent run handles each stage and passes work to the next through comments on the GitHub issue, so no stage depends on a long chat. You review at two points and merge yourself.

```
idea -> issue -> analyze -> decide -> [Gate A] -> plan -> phase 1..N -> test -> review [-> fix -> test -> review] -> docs -> [Gate B]
```

## Requirements

- Python 3.12 or newer. The pipeline itself needs no packages; `pytest` is only for tests.
- `git`, `gh` (logged in), and the `claude` CLI (logged in).

## Install

```sh
cd pipeline
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Use

Run from the repository you want to change. Its working tree must be clean.

```sh
pipeline run "Add a dark mode toggle"
pipeline run --issue 42
pipeline run --resume add-a-dark-mode-toggle
pipeline run "Add a dark mode toggle" --dry-run
```

| Option | Effect |
|---|---|
| `--issue REF` | Start from an existing GitHub issue (number or URL) instead of an idea. Skips the issue stage and starts at analyze. |
| `--resume SLUG` | Continue an earlier run. Stages that already have a comment are skipped. |
| `--dry-run` | Use a fake agent and fake GitHub in a temp directory. Nothing is spent or pushed. |
| `--repo PATH` | Target repository. Default: current directory. |
| `--stop-after STAGE` | Stop once that stage finishes, for example `plan`. |

The run asks `y/N` after every stage. At the two gates it also shows what you must review. After `plan` it shows the phase titles, `## Assumptions` and `## Out of scope` first, so you can decline before any code is written.

## Stages and comments

Each stage's output is one comment on the issue. A comment starts with a hidden marker (`<!-- pipeline:artifact=<name> -->`) and a `## <Name>` heading, then the agent's text. The issue body is the issue stage's output. Nothing under `.agent/runs/` is committed, so the PR diff holds only real changes.

Before a stage runs, the pipeline copies its input comments into a temp folder outside the repo and gives the agent those file paths. The skill for each stage is in [`skills/`](../skills).

| Stage | Skill | Model | Reads | Posts |
|---|---|---|---|---|
| issue | `forge-cli` | sonnet | the idea | the issue body |
| analyze | `analyze` | opus | issue | `analysis` |
| decide | `decide` | opus | issue, analysis | `decisions` |
| plan | `plan` | opus | issue, analysis, decisions | `plan` |
| implement-phase-N | `implement-phase` | sonnet | plan, earlier summaries | `phase-N-summary` |
| test | `test` | sonnet | plan, summaries | `test-report` |
| review | `review` | opus | issue, plan, summaries, test report | `review` |
| fix | `fix` | sonnet | issue, plan, test report, failed review | `fix-summary` |
| revise | `revise` | sonnet | issue, plan, test report, review, pr, earlier revisions | `revision-N` |
| docs | `docs` | sonnet | plan, summaries, test report, review | `pr` |

`review` cannot edit files. It labels findings Critical, Required or Nit and starts with `Status: pass`, or `Status: fail` if any finding is Critical or Required. A fail runs one fix round: `fix` applies the Critical and Required findings, then `test` and `review` run again, with the review also reading `fix-summary`. If any of the three blocks or fails, the run stops and `docs` does not run until `--resume` passes the review. A `--resume` after a failed review starts with another fix round, not a fresh review, and the review after it reads the failed `review.blocked` so its findings carry over.

`decide` sorts each open question into one of three groups: decided from code, decided and recorded as low-risk, or escalated to you.

After `analyze`, `decide` and `plan` the pipeline checks the reply before posting it:

- `analyze` needs an `## Open questions` section, numbered `Q1`, `Q2`, ... or `None.`.
- `decide` needs `## Decided from evidence`, `## Decided, low stakes` and a readable `## Escalated`, with a decision for every `Q#` in the analysis.
- `plan` needs a `Verify:` line in every phase with no manual step in it, and an `## Acceptance criteria` section that maps each criterion to an existing `Phase N` or marks it `Manual:`.
- Every backticked `path:line` reference in the `analyze` or `decide` reply must point to an existing file and a line inside it.

A failing reply is sent back once with the list of problems. If it still fails, the run stops and the reply is posted as the `<stage>.blocked` comment; `--resume` runs the stage again. The retry is billed like any other call.

A comment over GitHub's 65,536-character limit stops the run with an error naming the artifact.

`test` fails when an acceptance criterion has no covering test, or when its test still passes after `test` breaks the behavior on purpose. In a repo with Playwright, a criterion a browser can check must have a passing Playwright spec; `implement-phase` writes and runs those specs too. `test` and `review` also check the work against `DEFINITION_OF_DONE.md` in the target repo's root. Without that file they use the 8-line default in [`skills/DEFINITION_OF_DONE.md`](../skills/DEFINITION_OF_DONE.md). Unmet items appear in their reports.

## Gates

- **Gate A**, after `decide`: the run prints the decided items, then the open part of the `## Escalated` section of the `decisions` comment. It stops, even if you approve, while any escalated question is unanswered, and errors if `## Escalated` is missing or unreadable. The run asks for each open question in the terminal: type an answer, `r` to accept the recommendation, `m` for a multi-line answer (end with a blank line), or Enter to skip. Start with `!` when the answer changes an earlier decision: `decide` then reruns once with the answers and revises the affected items. Answers are written back to the comment. You can also edit the comment on GitHub, or reply in a new comment. After you approve, the plan stage reads the edited comment and any later replies.
- **Gate B**, after `docs`: the run prints the `pr` comment. Approving puts its current text in the PR description and marks the PR ready. Merging is still manual. Answering `N` offers a feedback prompt (Enter to stop, `m` for multi-line); feedback runs [revise](#revise).

## Revise

```sh
pipeline revise <slug> "Confirm delete in a modal, not inline"
```

For changes you want after the run, such as UI or UX you dislike. Run it from the target repo any time before you merge. It also runs when you decline Gate B and type feedback.

`revise` takes your feedback as the spec: it writes a failing test, changes the code, and posts a `revision-N` comment (feedback, changes, new acceptance criteria). Then `test`, `review` and `docs` run again, each reading the revision, and Gate B asks again. Each step is committed to the same branch. A blocked or failed step stops the run; reply on the issue or run `revise` again with clearer feedback.

## What lands on GitHub

- An issue (or the one you passed with `--issue`) holding one comment per stage.
- A branch `agent/<slug>`. Each finished stage is committed and pushed if it changed files. Phase commits are titled `phase N: <title from the plan>`; others are `pipeline: <stage>`.
- A draft PR, opened at the first push with commits beyond the default branch. It links to the issue.

`.agent/runs/<slug>/state.json` stays on your machine, untracked. It holds the issue URL, PR URL and idea.

## Resume

`--resume <slug>` skips every stage whose comment already exists. Re-running a stage edits its comment instead of adding a second one. Both gates are asked again.

After a failed review, reply on the issue to accept a finding or confirm a manual check. On resume, the fix stage and the re-review read every reply posted after the `review.blocked` comment, and neither blocks on a finding you accepted.

## Cost controls

- `BUDGET_USD` sets the spend limit per issue. Default: 15 (US dollars).
- Before each stage the run stops if spend is over the limit. During a stage, the agent's cap is the remaining budget.
- Each stage has its own turn cap (10 to 60 turns) and a 30-minute timeout.
- When a run ends, for any reason, it posts or edits one `cost` comment on the issue. The comment holds a table of stage, model and cost, plus the total and the budget. If posting fails, the table is printed to stderr.
- A resumed run starts from the total in that comment.
- `implement-phase-N` must start its report with `Status: done` or `Status: blocked`, and `test` and `review` with `Status: pass` or `Status: fail`. A `blocked` or `fail` status, or a first line that is none of the allowed values, stops the run and nothing is committed for that stage. The report is posted as the `<stage>.blocked` comment. `--resume` runs that stage again.

## Evals

```sh
pipeline eval [--case NAME]
```

Runs the real `decide` and `plan` skills on the fixture cases in `evals/cases/` and prints a score. **It spends money** (each case makes two opus calls, capped at $2 each) and is not part of `pytest` or CI. Each case has an issue, an analysis, a decisions comment for the plan step, and `expected.json`, which lists the buckets allowed for each question. A case passes when:

- every question lands in an allowed bucket (for example, a question about a public API must be escalated), and
- the decisions pass the structure check above (headings present, every `Q#` answered), and
- the plan passes the plan check above (numbered phases, automated `Verify:` lines, acceptance criteria mapped to phases).

Baseline (2026-10-17, before the anti-rationalization tables): 4/4 cases clean, about $1.64 for the four cases.

After the anti-rationalization tables (2026-10-17): 4/4 cases clean, $1.67. No change; the fixtures were already passing, so they cannot show gains.

```sh
pipeline eval --suite review [--case NAME]
```

Runs the real `review` skill (one opus call per case, capped at $2) on the cases in `evals/review/`. Each case is a small repo: `base/` is committed on `main` and `head/` on a `feature` branch. The case also holds the issue, plan, phase summary and a passing test report. The fixture tests pass, so the planted bug is visible only on review. `expected.json` gives the expected status and the `file` and `lines` of each planted bug. A case passes when:

- the status matches, and
- every planted bug is cited by a Critical or Required finding (a `file:line` inside its lines), and
- the `clean` case has no Critical or Required finding.

| Case | Planted bug |
|---|---|
| `sql-injection` | Email put into an SQL string |
| `boundary` | `>` where the issue says "$100 or more"; the tests skip 100 |
| `pattern-sweep` | Unescaped user text in three places across two files |
| `duplicate-helper` | Re-implements the existing `slugify` |
| `clean` | None |
| `css-layer` | A selection rule in `@layer utilities` that the unlayered global `::selection` overrides, so it never applies (#256) |
| `class-only-test` | A loading state that only adds a class; the button can still be clicked, and the test checks only the class |
| `untouched-instance` | The issue says escape usernames everywhere; the diff fixes one function and leaves the same bug in an unchanged one (#260) |
| `noisy-diff` | 0-based page offset in a 1-based `paginate`, inside a 100-line diff of helpers, export and docs |

Baseline (2026-10-22, one run per case): the current skill scores 9/9, $2.56. The skill before the axis checklists and pattern rule (`bc575f8^`) scores 8/9, $2.36. Its one fail, `class-only-test`, found the bug but put a sentence before `Status:`, which stops a real run. No case yet separates the two skills on what they find.

## Skills

The pipeline passes each agent the full path to its skill file, so no install is needed.

To use the new skills in interactive Claude Code sessions, link the ones you do not already have:

```sh
for skill in analyze decide plan implement-phase test review fix docs; do
  [ -e ~/.claude/skills/$skill ] || ln -s "$PWD/skills/$skill" ~/.claude/skills/$skill
done
```

The skills are plain Markdown, so any agent can follow one if you point it at the file. Only `ClaudeAgent` exists. To support another agent, write a class with `run(prompt, model, budget) -> Result` and pass it to `Pipeline`.

## Limits

- Checked against a live `claude` 2.1.289 run in a scratch repo: `--max-turns` and `--max-budget-usd` are accepted, and the JSON `result` and `total_cost_usd` fields parse. Not checked: what happens when a cap is hit, and a full pipeline run.
- `ClaudeAgent` passes `--permission-mode auto`, so a classifier approves routine edits and commands instead of prompting. Set `PIPELINE_PERMISSION_MODE=acceptEdits` to fall back to the stricter mode, where shell commands are refused unless allowed. `git commit` and `git push` are always denied; the pipeline does those. The pipeline passes `--allowedTools` from `src/pipeline/permissions.py`: read-only `git`/`gh`/`ls`/`grep`/`cat` for every stage, plus common test, lint and build runners (pytest, npm, npx vitest/tsc/eslint/playwright, go, cargo) for the stages that write. It never allows `git commit` or `git push`; the pipeline does those. Agents run one command at a time from the repo root, so skills use `npm --prefix <dir> ...` rather than `cd <dir> && ...`.
- A target repo adds its own commands in `.pipeline.json` at its root, for example `{"allowedTools": ["Bash(make check:*)"]}`. These apply to writing stages only. When claude is denied a command anyway, the pipeline prints the command and this fix to stderr. If the stage then ends `blocked`, the run asks in the terminal whether to allow each denied command: `y` for the rest of this run, `a` to also save the rule to `.pipeline.json`, Enter to skip. After any approval the stage reruns instead of posting the `.blocked` comment.
- The headless shell has no nvm. The pipeline reads the target repo's `.nvmrc` (root or one folder down), picks the newest matching `~/.nvm/versions/node/v<major>.*`, and puts its `bin` first on the agent's `PATH`; it stops if that version isn't installed. Set `PIPELINE_NODE_BIN` to override.
- Not built: automatic continuation past the gates, a GitHub Actions trigger, and a Codex adapter.

## Test

```sh
.venv/bin/python -m pytest
```

Run it from the `pipeline` folder.
