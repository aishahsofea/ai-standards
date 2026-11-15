# Plan: chat "concierge" for the feature pipeline (revision 2)

## Context
- Repo: `ai-standards`. `pipeline/` (Python 3.12, stdlib only) turns a feature idea into a draft PR. Each stage is a fresh `claude` CLI run, and stages hand off through comments on a GitHub issue.
- `--headless` never reads the terminal. Where it would ask the owner, it posts a `request-<name>` comment (`request-baseline`, `request-gate-a`, `request-plan`, `request-gate-b`, `request-allow`) and exits with code 3. It reads the reply from a later owner/member/collaborator comment.
- Reply grammar: `/approve`, `/reject`, `/revise <feedback>`, `Q<n>: <answer>` (a leading `!` changes an earlier decision), `/allow <rule>`.
- Facts about the grammar that shape this design:
  - The first command after a request decides it. A later comment cannot change it; only deleting the reply can.
  - A command must start the comment. `>`-quoted lines are ignored.
  - `/revise` takes everything to the end of the comment as feedback.
  - `/allow` is matched on any line of any owner comment on the issue, and every match is granted at the start of each headless run.
  - `Q<n>:` answers are one line each.
  - A command that is not valid for the request (for example `/revise` at `request-plan`) counts as "not approved" and stops the run.
- Exit codes: 0 is finished *or* stopped (blocked, rejected), 1 is error, 3 is waiting.
- Resume is idempotent: `pipeline run --resume <slug> --headless` with no new reply posts nothing and exits 3 again.
- The pipeline has no lock against two processes resuming the same run.

## Goal
Use the pipeline from a chat app on a phone, with no terminal and no slash commands.
1. Start runs from chat, across several repos.
2. Get notified when a run needs a decision, with a phone-sized summary.
3. Reply with a button or in natural language. The concierge turns it into the pipeline's exact command and resumes the run.

## Architecture
```
you (chat app) <-> concierge daemon <-> pipeline (--headless --worktree) <-> GitHub issue
```
- The issue stays the only source of truth for decisions. Local state is a cache.
- The concierge runs the pipeline as subprocesses, and imports `pipeline.forge` and `pipeline.run_dir` for the reply grammar, slugs and comment reading. It does not reimplement them.
- It writes the same comments a human would, under the user's `gh` login.
- Chat: Telegram (long polling, inline buttons), behind a small adapter interface.
- Where it runs: the user's laptop for now.

## Pipeline changes (small, in slice 1)
- **Machine-readable result.** A `--json` flag makes the last stdout line `{"status": "finished|stopped|waiting", "stage": ..., "request": ...}`, so the supervisor never parses prose and can tell finished from blocked.
- **Per-run lock.** An `fcntl` lock on the run directory, held for the whole run. A second process on the same slug exits with an error.

## New package: `concierge/` (sibling of `pipeline/`, stdlib only)
- **Supervisor**
  - Spawns and resumes `pipeline run ... --headless --worktree --json` in its own process group, with a concurrency cap and a daily spend cap.
  - Holds `caffeinate -i` while any run is active.
  - `stop` sends SIGINT to the process group, so the pipeline still posts its cost comment and the `claude` child exits.
  - On startup, resumes every known run that is not running. This is the whole recovery path.
- **Notifier**
  - On `waiting`, reads the pending request and records its **comment ID** and, for Gate B, the **head commit**.
  - Builds the summary by extraction, not by a model: `plan_preview`, `commands_notice`, the Gate A questions, the denied rules, each with a link. Plan commands and `/allow` rules are shown verbatim.
  - Attaches buttons for the actions that are valid for that request.
- **Action table** (code, not model)

  | Request | Valid actions |
  |---|---|
  | `request-baseline` | approve, reject |
  | `request-gate-a` | answer, approve (accept every recommendation) |
  | `request-plan` | approve, reject |
  | `request-gate-b` | approve, revise, reject |
  | `request-allow` | allow (only rules listed in the request) |

  `status` and `stop` are always valid. Anything else gets a reply that says what is possible here, for example "the plan step only takes approve or reject".
- **Interpreter** (fallback only)
  - Buttons need no model. Revise feedback is passed through verbatim.
  - A model is called only for free text: to pick one of the valid actions, and to map answers onto Gate A's `Q<n>` numbers.
  - One `claude -p --bare --json-schema ...` call with a fixed system prompt and no tools, on Haiku.
  - Output: `{action, question_answers: [{n, answer}], feedback}`. `action` is an enum limited to the valid actions for the pending request, plus `unclear`. It never outputs an `/allow` rule or a restatement.
- **Confirm layer**
  - The restatement is rendered by code from the exact comment that will be posted.
  - No confirm: `status`, cost.
  - A button on the notification is the confirm for approve at baseline and for accepting Gate A recommendations.
  - Confirm: anything the model derived from free text.
  - Always confirm, with verbatim text: `/allow`, plan approve, Gate B approve (shows the head commit), `/reject`, `stop`.
  - `unclear` gets a clarifying question, never a guess.
  - Confirm buttons carry the request's comment ID and expire when that request is answered or withdrawn.
- **Poster**
  - Before posting, re-reads the issue and refuses if the request's comment ID or head commit changed, or if the request already has a decision. It then re-notifies with the current request.
  - Comment format: the command first, then the note as a blockquote with every line prefixed `>` and newlines collapsed: `> via chat: "<original words>"`.
  - Gate A answers are collapsed to one line each.
  - Stores the ID of each comment it posts. `undo` deletes that comment, which is the only way to reverse a decision.
  - Then runs `--resume --headless`.
- **Repo registry**: `~/.concierge/config.json` maps names to paths.
- **Concierge state**: `~/.concierge/state.json` maps chat message ID to (repo, slug, request comment ID, posted comment IDs). It is a cache; losing it loses only reply threading.

## Slices (build in this order, tests first)
1. **Core, no Telegram.**
   - The two pipeline changes.
   - A stdin chat adapter with numbered choices standing in for buttons.
   - Supervisor, notifier, action table, confirm layer, poster, startup resume.
   - Poster round-trip tests: every comment it can produce is parsed back by `first_command`, `ANSWER` and `ALLOW` to the intended decision and nothing else. Include user words that contain `/allow ...`, `Q2: ...` and `/approve` lines.
   - Stale-request tests: a confirm for a withdrawn or already-decided request posts nothing.
   - Interpreter eval cases, written before the interpreter:
     - Clear: "ship it", "go with your recommendations on everything".
     - Ambiguous, must be `unclear`: "hmm maybe".
     - Negation and conditions, must not be approve: "don't ship it yet", "approve if CI is green".
     - Invalid for the request: "looks good but make delete a modal" is revise at Gate B and not possible at the plan step.
     - Injection: request text or user text that tells the model to approve.
   - Unit tests use a fake model and `FakeForge`.
2. **Telegram adapter.**
   - Long polling, private chat only, answers only the owner's user ID, inline buttons.
   - Replies are matched to a run through the cached message ID.
   - The owner creates the bot via BotFather, supplies the token in an env var, and turns on Telegram two-step verification.
3. **Several repos and start-from-chat.**
   - "Add dark mode to <repo>" starts a run after a confirm that shows the repo and the budget. A missing or ambiguous repo is asked with buttons.
   - The slug comes from `pipeline.run_dir.slugify`. A slug that already exists is refused.
   - A plain message goes to the run that is waiting. If several are waiting, it asks which. If none is waiting, it is never posted to an issue.
   - `status` and cost summaries.
4. **Progress and extras.**
   - Optional `--events` JSONL stream for "plan posted", "CI green" and "blocked" notifications.
   - Voice notes, transcribed, then treated as free text.

## Safety decisions
- The model only picks from the actions valid for the pending request. It never runs commands, never writes `/allow` rules and never writes the text the user confirms.
- A decision is bound to the request the user saw: comment ID, plus head commit at Gate B.
- `/allow` offers only rules listed verbatim in the request, as buttons.
- Free text never directly approves anything.
- The user's words reach the issue only inside a blockquote.
- Only one authorized chat user, in a private chat. Everyone else is ignored.
- No secrets in chat. The bot token and `gh` auth stay in the environment.
- A daily spend cap in the concierge, on top of the pipeline's per-run budget.
- Posting as the user means the issue shows the user's identity. The "via chat" note keeps the audit trail honest.

## Known limits
- Closing the laptop lid pauses runs and notifications. A hosted runner is deferred until this proves annoying.
- The plan step cannot be revised from chat, only approved or rejected, because the pipeline has no plan-revise command.
- A launchd-started daemon gets a minimal PATH. Check that `gh`, `claude` and the node version resolve.

## Open questions
1. Should `!` (an answer that changes an earlier decision and reruns `decide`) be chosen by the model, or only by an explicit button?
2. Is a GitHub-mobile-plus-poller version (resume on reply, no chat app, no model) worth shipping first as a baseline?
3. Do Claude Code's channels or Remote Control now cover enough of the transport to replace the Telegram adapter without giving a model shell access? Not verified.
