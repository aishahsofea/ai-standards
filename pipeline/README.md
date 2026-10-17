# Feature pipeline

Takes a feature idea and produces a draft pull request. A fresh agent run handles each stage and passes work to the next through files, so no stage depends on a long chat. You review at two points and merge yourself.

```
idea -> issue -> analyze -> decide -> [Gate A] -> plan -> phase 1..N -> test -> docs -> [Gate B]
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
| `--resume SLUG` | Continue an earlier run. Finished stages are skipped. |
| `--dry-run` | Use a fake agent and fake GitHub in a temp directory. Nothing is spent or pushed. |
| `--repo PATH` | Target repository. Default: current directory. |
| `--stop-after STAGE` | Stop once that stage finishes, for example `plan`. |

The run asks `y/N` after every stage. At the two gates it also shows what you must review.

## Stages and files

Each stage reads and writes files in `.agent/runs/<slug>/` in the target repo. The skill for each stage is in [`skills/`](../skills).

| Stage | Skill | Model | Reads | Writes |
|---|---|---|---|---|
| issue | `forge-cli` | sonnet | the idea | `issue.md` |
| analyze | `analyze-issue` | opus | `issue.md` | `analysis.md` |
| decide | `decide` | opus | issue, analysis | `decisions.md` |
| plan | `plan` | opus | issue, analysis, decisions | `plan.md` |
| implement-phase-N | `implement-phase` | sonnet | plan, earlier summaries | `phase-N-summary.md` |
| test | `test` | sonnet | plan, summaries | `test-report.md` |
| docs | `docs` | sonnet | plan, summaries, test report | `pr.md` |

`decide` sorts each open question into one of three groups: decided from code, decided and recorded as low-risk, or escalated to you.

## Gates

- **Gate A**, after `decide`: the run prints the `## Escalated` section of `decisions.md`. Write your answer on each `Answer:` line, then approve.
- **Gate B**, after `docs`: the run prints the PR text. Approving puts it in the PR description and marks the PR ready. Merging is still manual.

Resuming asks both gates again.

## What lands on GitHub

- An issue created from `issue.md`.
- A branch `agent/<slug>`. Every finished stage is committed and pushed, so the artifacts are in the PR.
- A draft PR opened after the first push. It links to the issue, and the issue gets a comment pointing to the run files.

## Cost controls

- `BUDGET_USD` sets the limit for a feature. Default: 15 (US dollars).
- Before each stage the run stops if spend is already over the limit. After a stage starts, the agent is given the remaining budget as its own cap.
- Each stage has its own turn cap (10 to 60 turns) and a 30-minute timeout.
- Every stage's cost is added to `cost.csv` in the run folder. A resumed run counts what it spent before.
- If a stage's report starts with `Status: blocked` or `Status: fail`, the run stops. The report is saved as `<stage>.blocked.md`, and `--resume` runs that stage again.

## Skills

The pipeline passes each agent the full path to its skill file, so no install is needed.

To use the new skills in interactive Claude Code sessions, link the ones you do not already have:

```sh
for skill in decide plan implement-phase test docs; do
  [ -e ~/.claude/skills/$skill ] || ln -s "$PWD/skills/$skill" ~/.claude/skills/$skill
done
```

The skills are plain Markdown, so any agent can follow one if you point it at the file. Only `ClaudeAgent` exists. To support another agent, write a class with `run(prompt, model, budget) -> Result` and pass it to `Pipeline`.

## Limits

- `claude -p` can't edit files or run commands without permission. `ClaudeAgent` passes no permission flags, so the target repo's `.claude/settings.json` needs allow rules. Not yet tested end to end.
- The `--max-turns` and `--max-budget-usd` flags have not been checked against a live `claude` run.
- Not built: automatic continuation past the gates, a GitHub Actions trigger, and a Codex adapter.

## Test

```sh
.venv/bin/python -m pytest
```

Run it from the `pipeline` folder.
