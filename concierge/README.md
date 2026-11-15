# Concierge

Runs the [feature pipeline](../pipeline/README.md) from a chat app. Design and slices: [PLAN.md](PLAN.md). Python 3.12, stdlib only; it imports `pipeline` for the reply grammar, slugs and comment reading.

## Develop

```sh
cd concierge
python3 -m pytest -q          # pytest finds ../pipeline/src through pyproject
python3 -m concierge eval     # scores evals/interpreter.json and evals/start.json with the real model (spends cents)
```

Config is `~/.concierge/config.json` (`CONCIERGE_HOME` overrides the folder): `{"repos": {"shop": "~/code/shop"}, "max_concurrent": 2, "daily_cap_usd": 30, "telegram_owner_id": 123456789, "transcribe_command": ["~/bin/transcribe", "{audio}"]}`. `transcribe_command` is optional; see [Voice notes](#voice-notes).

```sh
python3 -m concierge serve --start shop "Add dark mode"
```

## Telegram setup

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token it gives you.
2. Export it where `serve` runs: `export CONCIERGE_TELEGRAM_TOKEN=<token>`. Keep it out of the config file, the repo and the chat.
3. Message [@userinfobot](https://t.me/userinfobot) to get your numeric user ID, then add `"telegram_owner_id": <id>` to `~/.concierge/config.json`.
4. In Telegram, go to Settings → Privacy and Security → Two-Step Verification and turn it on. The bot only answers your user ID, but anyone who takes over your account can use it.
5. Run `python3 -m concierge serve`, open a private chat with your bot and press Start. With no token or no owner ID, `serve` falls back to the terminal.

The bot ignores every other user, group, channel, edited message and any message that is not text or a voice note. Send replies as Telegram replies to the notification so they reach the right run.

## Voice notes

A voice note from you is handled as if you had typed what it says. It is off until `transcribe_command` is set in `config.json`; without it the bot replies that voice is not set up.

- `transcribe_command` is a list of arguments, run without a shell, that must print the transcript on stdout. `{audio}` in any argument is replaced by the path of the downloaded `.ogg` file; with no `{audio}` the path is added as the last argument. A leading `~` in an argument is expanded. It is stopped after 120 seconds.
- Nothing is sent to a third party. The concierge downloads the note from Telegram (the `getFile` call, then the file URL, at most 10 MB) and gives it to your command. Telegram's voice notes are Opus in an Ogg container. `whisper-cli` wants WAV, so point the command at a small script that runs `ffmpeg -i "$1" -ar 16000 -ac 1 "$1.wav"` and then `whisper-cli -m <model> -nt -f "$1.wav"`.
- The bot first sends `Heard: "<transcript>"`, then handles the transcript exactly like free text: the same routing, interpreter and confirm layer. A mistranscription can only produce a confirm you can cancel; nothing is posted without Confirm.
- One difference from typed text: a transcript of `undo` is refused, because `undo` deletes a comment without a confirm. Type it.
- A note that is over the size cap, cannot be fetched, fails to transcribe or is silent gets a one-line reply and goes nowhere.

## Progress events

For each run the concierge starts, the pipeline is run with `--events <home>/logs/<repo>-<slug>.events.jsonl`. After each poll the concierge reads the new complete lines, remembers the byte offset in `state.json` (so a restart never repeats a message) and sends one short message without a notification sound for `plan-posted` ("plan posted"), `ci-green` ("CI green") and `blocked` ("blocked: <stage>"). Other events are ignored. These messages never carry buttons, create nothing a reply can attach to and post nothing to the issue. A malformed line is skipped; a half-written last line waits until it ends with a newline.

When a run stops at a stage that posted a `<stage>.blocked` report, the stop message adds the report's status line, its `Unblock:` line if it has one, and a link to the comment. A message sent while nothing is waiting repeats that for every stopped run.

## Modules

| Module | Role |
|---|---|
| `app.py` | `Concierge`: routes chat events, the confirm layer, `main` |
| `supervisor.py` | Spawns and resumes `pipeline run ... --headless --worktree --json --events <log>`, caps, `caffeinate`, startup recovery; `poll` returns `Outcome`s and `Progress` events |
| `notifier.py` | `build_prompt(request, comments)` returns the phone-sized summary and `Choice` buttons |
| `poster.py` | Re-reads the issue and posts only if the request is unchanged and undecided; `undo` |
| `actions.py` | Action table, `render_comment` (the only place comment text is made) |
| `interpreter.py` | `Interpreter` protocol (`interpret`, `start_intent`), `ClaudeInterpreter`, `sanitize` and `sanitize_start` guards |
| `requests.py` | Finds the pending request, its decision, rules and open questions in issue comments |
| `telegram.py` | `TelegramChat`: Bot API long polling, inline buttons, owner-only, voice download; `bot_http` and `bot_download` are the only code that holds the token |
| `voice.py` | `Transcriber` protocol (`transcribe(audio) -> str`), `CommandTranscriber` (runs your local command) |
| `chat.py` | `Chat` protocol (`send(text, choices, silent) -> message_id`, `poll(timeout) -> [Event]`), `StdinChat` |
| `issue.py` | `GitHubIssue`, the `gh` gateway for one run |
| `state.py` | `~/.concierge/state.json`, a cache keyed by chat message id |

Tests use `tests/fakes.py` (`FakeIssue`, `FakeSpawn`, `FakeProcess`) and the fakes at the top of `tests/test_app.py` (`FakeChat`, `FakeInterpreter`, `World`).

## Behaviour worth knowing

- Chat adapters implement `Chat`. `send(..., silent=True)` sends without a notification sound. A voice note is `Event("voice", audio=<bytes>, message_id=...)`, or with `audio` empty and `text` giving the reason it could not be fetched. A button click is `Event("button", data=..., message_id=<message the button was on>)`; free text is `Event("text", text=..., message_id=<replied-to message or None>)`. `Choice.data` is one of `approve`, `reject`, `revise`, `allow:<i>`, `confirm`, `cancel`.
- `status`, `cost`, `stop [repo/slug]` and `undo` are matched in code before any model call. `status` groups runs by repo with each run's spend; `cost` shows today's spend against the daily cap and per-run totals.
- A free-text message that is not a reply and not feedback first goes through `Interpreter.start_intent`, which returns `start`, `other` or `unclear` plus a configured repo name (or empty) and an idea. The model never writes text the user sees.
  - `start` shows a code-rendered confirm with the repo, the idea, the per-run budget (`BUDGET_USD`, default from `pipeline.cost`) and the remaining daily cap. Nothing runs until Confirm. A missing, unknown or ambiguous repo is asked with one button per configured repo.
  - A slug that already exists, an idea starting with `-` (the pipeline would read it as an option) and a reached daily cap are refused with a message, before the confirm and again on Confirm.
  - The idea reaches `pipeline run` only as one argv item, never a comment, so `/allow ...` inside it does nothing.
  - A start confirm or repo picker expires when used, cancelled or replaced by a newer start request, and it survives a restart. It never touches a waiting request.
  - `other` goes to the waiting-run routing below. `unclear` with a run waiting asks you to reply to the request message and posts nothing; with none waiting it is the same "nothing was posted" reply.
- A plain message goes to the run that is waiting when exactly one is; with several it asks; with none nothing is posted to an issue. Replies to a message, and feedback after Revise, skip the start check.
- Confirm buttons and request buttons expire when the run's request is answered (`State.drop_messages`).
- `--bare` is passed to `claude` only when `ANTHROPIC_API_KEY` is set, because `--bare` ignores the logged-in session.
- The pipeline's `--json` line also carries `spent_usd` (the issue's running total); the supervisor turns it into the daily spend.
- Button-started and text-started `/revise` both ask for confirmation, a little stricter than the plan.
