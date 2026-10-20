# Feature pipeline

Takes a feature idea and produces a draft pull request. A fresh agent run handles each stage and passes work to the next through comments on the GitHub issue, so no stage depends on a long chat. You review at two points and merge yourself.

```
idea -> issue -> analyze -> decide -> [Gate A] -> plan -> phase 1..N -> test -> review -> docs -> [Gate B]
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
| analyze | `analyze-issue` | opus | issue | `analysis` |
| decide | `decide` | opus | issue, analysis | `decisions` |
| plan | `plan` | opus | issue, analysis, decisions | `plan` |
| implement-phase-N | `implement-phase` | sonnet | plan, earlier summaries | `phase-N-summary` |
| test | `test` | sonnet | plan, summaries | `test-report` |
| review | `review` | opus | issue, plan, summaries, test report | `review` |
| docs | `docs` | sonnet | plan, summaries, test report, review | `pr` |

`review` cannot edit files. It labels findings Critical, Required or Nit and starts with `Status: pass`, or `Status: fail` if any finding is Critical or Required. A fail stops the run like a failed test, and `docs` does not run until `--resume` passes the review.

`decide` sorts each open question into one of three groups: decided from code, decided and recorded as low-risk, or escalated to you.

A comment over GitHub's 65,536-character limit stops the run with an error naming the artifact.

`test` and `review` also check the work against `DEFINITION_OF_DONE.md` in the target repo's root. Without that file they use the 8-line default in [`skills/DEFINITION_OF_DONE.md`](../skills/DEFINITION_OF_DONE.md). Unmet items appear in their reports.

## Gates

- **Gate A**, after `decide`: the run prints the `## Escalated` section of the `decisions` comment. The run asks for each open question in the terminal: type an answer, `r` to accept the recommendation, or Enter to skip. Answers are written back to the comment. You can also edit the comment on GitHub, or reply in a new comment. After you approve, the plan stage reads the edited comment and any later replies.
- **Gate B**, after `docs`: the run prints the `pr` comment. Approving puts its current text in the PR description and marks the PR ready. Merging is still manual.

## What lands on GitHub

- An issue (or the one you passed with `--issue`) holding one comment per stage.
- A branch `agent/<slug>`. Each finished stage is committed and pushed if it changed files. Phase commits are titled `phase N: <title from the plan>`; others are `pipeline: <stage>`.
- A draft PR, opened at the first push with commits beyond the default branch. It links to the issue.

`.agent/runs/<slug>/state.json` stays on your machine, untracked. It holds the issue URL, PR URL and idea.

## Resume

`--resume <slug>` skips every stage whose comment already exists. Re-running a stage edits its comment instead of adding a second one. Both gates are asked again.

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
- the plan has numbered phases and every phase has a `Verify:` line.

Baseline (2026-10-17, before the anti-rationalization tables): 4/4 cases clean, about $1.64 for the four cases.

After the anti-rationalization tables (2026-10-17): 4/4 cases clean, $1.67. No change; the fixtures were already passing, so they cannot show gains.

## Skills

The pipeline passes each agent the full path to its skill file, so no install is needed.

To use the new skills in interactive Claude Code sessions, link the ones you do not already have:

```sh
for skill in decide plan implement-phase test review docs; do
  [ -e ~/.claude/skills/$skill ] || ln -s "$PWD/skills/$skill" ~/.claude/skills/$skill
done
```

The skills are plain Markdown, so any agent can follow one if you point it at the file. Only `ClaudeAgent` exists. To support another agent, write a class with `run(prompt, model, budget) -> Result` and pass it to `Pipeline`.

## Limits

- Checked against a live `claude` 2.1.289 run in a scratch repo: `--max-turns` and `--max-budget-usd` are accepted, and the JSON `result` and `total_cost_usd` fields parse. Not checked: what happens when a cap is hit, and a full pipeline run.
- `ClaudeAgent` passes `--permission-mode acceptEdits`, so agents can edit files. Without it, `claude -p` refuses every edit. Shell commands are still refused unless the target repo's `.claude/settings.json` allows them, so add allow rules for the test command and any `git` or `gh` commands the skills use.
- Not built: automatic continuation past the gates, a GitHub Actions trigger, and a Codex adapter.

## Test

```sh
.venv/bin/python -m pytest
```

Run it from the `pipeline` folder.
