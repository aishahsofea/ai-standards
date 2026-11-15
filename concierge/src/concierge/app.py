import argparse
import hashlib
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from concierge.actions import Action, Answer, invalid_reason, render_comment
from concierge.chat import Chat, Event, StdinChat
from concierge.config import Config, home, load_config
from concierge.evals import render_results, run_cases, run_start_cases
from concierge.interpreter import UNCLEAR, ClaudeInterpreter, Interpreter
from concierge.issue import GitHubIssue
from concierge.notifier import Choice, build_prompt
from concierge.poster import Gateway, Poster, Refused
from concierge.requests import Request, blocked_note, decision_on, find_request, open_questions
from concierge.state import Bound, Message, RunId, State
from concierge.supervisor import Outcome, Progress, Supervisor, run_budget, spawn_local
from concierge.telegram import TelegramChat, bot_download, bot_http
from concierge.voice import CommandTranscriber, Transcriber, TranscriptionError

TOKEN_ENV = "CONCIERGE_TELEGRAM_TOKEN"
CONFIRM_CHOICES = (Choice("Confirm", "confirm"), Choice("Cancel", "cancel"))
ALWAYS_CONFIRM = {"allow", "reject", "revise"}
APPROVALS_NEEDING_CONFIRM = {"plan", "gate-b"}
NO_STAGE = Bound("", 0, "")
START_RUN = ""
BUTTON_ONLY = {"confirm", "pick-repo"}
PROGRESS_TEXT = {"plan-posted": "plan posted", "ci-green": "CI green", "blocked": "blocked: {stage}"}


def needs_confirm(key: str, action: Action, from_button: bool) -> bool:
    """A button is the confirm for approving at baseline and accepting Gate A's recommendations; free text never is."""
    return not from_button or action.kind in ALWAYS_CONFIRM or (action.kind == "approve" and key in APPROVALS_NEEDING_CONFIRM)


def action_from(data: dict) -> Action:
    return Action(data["kind"], tuple(Answer(**answer) for answer in data["answers"]), data["rule"], data["feedback"])


class Concierge:
    def __init__(
        self, state: State, supervisor: Supervisor, poster: Poster, chat: Chat, interpreter: Interpreter, gateway_for, transcriber: Transcriber | None = None
    ) -> None:
        self.state = state
        self.supervisor = supervisor
        self.poster = poster
        self.chat = chat
        self.interpreter = interpreter
        self.gateway_for = gateway_for
        self.transcriber = transcriber

    def start(self) -> None:
        self._announce(self.supervisor.recover())
        self.state.save()

    def tick(self, timeout: float = 1.0) -> None:
        for event in self.chat.poll(timeout):
            self.handle(event)
        self._announce(self.supervisor.poll())
        self.state.save()

    def handle(self, event: Event) -> None:
        match event.kind:
            case "button":
                self._button(event)
            case "voice":
                self._voice(event)
            case _:
                self._text(event)

    def _voice(self, event: Event) -> None:
        """The transcript is shown, then handled exactly like typed text, so the confirm layer still stands between it and the issue."""
        if self.transcriber is None:
            return self._say('Voice is not set up. Add "transcribe_command" to config.json (see the README).')
        if not event.audio:
            return self._say(f"I could not use that voice note: {event.text}.")
        try:
            transcript = self.transcriber.transcribe(event.audio).strip()
        except TranscriptionError as error:
            return self._say(f"I could not transcribe that voice note: {error}.")
        if not transcript:
            return self._say("I could not hear anything in that voice note.")
        self._say(f'Heard: "{transcript}"')
        self._text(Event("text", text=transcript, message_id=event.message_id), spoken=True)

    def _send(self, text: str, choices: tuple[Choice, ...] = ()) -> str:
        return self.chat.send(text, choices)

    def _say(self, text: str) -> None:
        self.chat.send(text)

    def _announce(self, updates: list[Outcome | Progress]) -> None:
        for outcome in updates:
            if isinstance(outcome, Progress):
                if text := PROGRESS_TEXT.get(outcome.event):
                    self.chat.send(f"{outcome.run}: {text.format(stage=outcome.stage)}", silent=True)
                continue
            run = outcome.run
            if outcome.status == "waiting":
                comments = self.gateway_for(run).comments()
                request = find_request(comments, outcome.request or "")
                if request:
                    self._notify(run, request, comments)
                else:
                    self._say(f"{run} is waiting at '{outcome.request}' but the request is not on the issue.")
                continue
            self.state.drop_messages(str(run))
            record = self.state.runs[str(run)]
            spent = f"${record.spent_usd:.2f}"
            match outcome.status:
                case "finished":
                    self._say(f"{run} finished. Spent {spent} in all.")
                case "stopped":
                    record.note = blocked_note(self.gateway_for(run).comments(), outcome.stage) if outcome.stage and not outcome.detail else ""
                    self._say("\n\n".join(filter(None, [f"{run} {outcome.detail or f'stopped at {outcome.stage}'}. Spent {spent} in all.", record.note])))
                case "capped":
                    self._say(f"{run} was not started: {outcome.detail}.")
                case _:
                    self._say(f"{run} failed: {outcome.detail}")

    def _notify(self, run: RunId, request: Request, comments, force: bool = False) -> None:
        prompt = build_prompt(request, comments)
        marker = f"{request.comment_id}:{hashlib.sha256(prompt.text.encode()).hexdigest()[:16]}"
        if not force and self.state.notified.get(str(run)) == marker:
            return
        self.state.drop_messages(str(run))
        message_id = self._send(f"{run}\n\n{prompt.text}", prompt.choices)
        self.state.messages[message_id] = Message(str(run), Bound(request.key, request.comment_id, request.digest, request.head), "request", rules=prompt.rules)
        self.state.notified[str(run)] = marker

    def _status(self) -> None:
        groups: dict[str, list[str]] = {}
        for name, record in self.state.runs.items():
            run = RunId.parse(name)
            at = f" at {record.request}" if record.request else ""
            groups.setdefault(run.repo, []).append(f"  {run.slug}: {record.status}{at}, ${record.spent_usd:.2f}")
        lines = [f"{repo}:\n" + "\n".join(runs) for repo, runs in groups.items()]
        cap = self.supervisor.config.daily_cap_usd
        self._say("\n".join([*(lines or ["No runs yet."]), f"Spent today ${self.supervisor.spent_today():.2f} of ${cap:.2f}"]))

    def _cost(self) -> None:
        totals = sorted(((name, record.spent_usd) for name, record in self.state.runs.items() if record.spent_usd), key=lambda total: -total[1])
        head = f"Spent today ${self.supervisor.spent_today():.2f} of ${self.supervisor.config.daily_cap_usd:.2f} (${self.supervisor.remaining_today():.2f} left)"
        self._say("\n".join([head, *(f"{name}: ${usd:.2f}" for name, usd in totals)] if totals else [head, "No run has spent anything yet."]))

    def _waiting(self) -> dict[str, Message]:
        return {m.run: m for m in self.state.messages.values() if m.kind == "request"}

    def _target(self, event: Event) -> Message | None:
        messages = self.state.messages
        if event.message_id is not None:
            message = messages.get(event.message_id)
            if message is None or message.kind in BUTTON_ONLY:
                self._say("That message is no longer active." if message is None else "Use the buttons on that message.")
            return message if message and message.kind not in BUTTON_ONLY else None
        if feedback := [m for m in messages.values() if m.kind == "feedback"]:
            return feedback[-1]
        waiting = self._waiting()
        if len(waiting) == 1:
            return next(iter(waiting.values()))
        self._say(f"Several runs are waiting: {', '.join(waiting)}. Reply to the message you mean." if waiting else self._nothing_waiting())
        return None

    def _nothing_waiting(self) -> str:
        stops = [f"{name} is stopped.\n{record.note}" for name, record in self.state.runs.items() if record.status == "stopped" and record.note]
        return "\n\n".join(["Nothing is waiting for a decision, so nothing was posted.", *stops])

    def _text(self, event: Event, spoken: bool = False) -> None:
        text = event.text.strip()
        word = text.lower().rstrip(".!? ")
        if word == "status":
            return self._status()
        if word == "cost":
            return self._cost()
        if word == "undo":
            return self._say("Type `undo` to undo; I do not delete a comment from a transcript.") if spoken else self._undo()
        if word == "stop" or word.startswith("stop "):
            return self._stop(text[4:].strip().rstrip(".!? "))
        if event.message_id is None and not any(m.kind == "feedback" for m in self.state.messages.values()) and self._start_intended(text):
            return
        if (message := self._target(event)) is None:
            return
        if message.kind == "feedback":
            return self._ask_confirm(message, Action("revise", feedback=text), text)
        self._interpret(message, text)

    def _start_intended(self, text: str) -> bool:
        """True when the message was handled as a new-run request or as too unsure to route anywhere."""
        intent = self.interpreter.start_intent(text, tuple(self.supervisor.config.repos))
        self.supervisor.add_spend(intent.cost_usd)
        if intent.kind == "start":
            self._propose_start(intent.repo, intent.idea, text)
        elif intent.kind == UNCLEAR and self._waiting():
            self._say("I cannot tell whether that starts a new run or answers one that is waiting. Reply to the request message to answer it, or say what to build and in which repo.")
        else:
            return False
        return True

    def _propose_start(self, repo: str, idea: str, words: str) -> None:
        self.state.drop_messages(START_RUN)
        if not repo:
            names = sorted(self.supervisor.config.repos)
            message_id = self._send(f"Which repo is this for?\n\n{idea}", tuple(Choice(name, f"repo:{n}") for n, name in enumerate(names)))
            self.state.messages[message_id] = Message(START_RUN, NO_STAGE, "pick-repo", {"idea": idea, "repos": names}, words)
            return
        if isinstance(run := self.supervisor.check(repo, idea), str):
            return self._say(f"Not started: {run}.")
        cap = self.supervisor.config.daily_cap_usd
        text = (
            f"Start a new run?\n\nRepo: {repo}\nIdea: {idea}\n"
            f"Budget: ${run_budget():.2f} for this run, ${self.supervisor.remaining_today():.2f} left of today's ${cap:.2f} cap"
        )
        confirm_id = self._send(text, CONFIRM_CHOICES)
        self.state.messages[confirm_id] = Message(START_RUN, NO_STAGE, "confirm", {"kind": "start", "repo": repo, "idea": idea}, words)

    def _interpret(self, message: Message, text: str) -> None:
        key, run = message.bound.key, RunId.parse(message.run)
        questions = open_questions(self.gateway_for(run).comments()) if key == "gate-a" else {}
        result = self.interpreter.interpret(text, key, questions)
        self.supervisor.add_spend(result.cost_usd)
        action = Action(result.action, result.answers, feedback=result.feedback)
        if reason := invalid_reason(key, action if result.action != UNCLEAR else Action(UNCLEAR)):
            prefix = "I could not tell what you meant" if result.action == UNCLEAR else "I cannot do that here"
            return self._say(f"{prefix}: {reason}.")
        self._ask_confirm(message, action, text)

    def _ask_confirm(self, message: Message, action: Action, words: str) -> None:
        head = f"\n\nHead commit: `{message.bound.head}`" if message.bound.key == "gate-b" else ""
        text = f"{message.run}: post this comment on the issue?\n\n{render_comment(action, words)}{head}"
        confirm_id = self._send(text, CONFIRM_CHOICES)
        self.state.messages[confirm_id] = Message(message.run, message.bound, "confirm", asdict(action), words)

    def _button(self, event: Event) -> None:
        message = self.state.messages.get(event.message_id or "")
        if message is None:
            return self._say("That button is no longer active.")
        if message.kind == "pick-repo":
            names = message.action["repos"]
            index = int(event.data.removeprefix("repo:")) if event.data.startswith("repo:") else -1
            return self._propose_start(names[index], message.action["idea"], message.words) if 0 <= index < len(names) else None
        if message.kind == "confirm":
            return self._confirmed(event.message_id or "", message) if event.data == "confirm" else self._cancelled(event.message_id or "")
        key = message.bound.key
        if event.data == "revise":
            feedback_id = self._send("Send your feedback as your next message.")
            self.state.messages[feedback_id] = Message(message.run, message.bound, "feedback")
            return
        rules = message.rules
        index = int(event.data.removeprefix("allow:")) if event.data.startswith("allow:") else -1
        action = Action("allow", rule=rules[index]) if 0 <= index < len(rules) else Action(event.data)
        if reason := invalid_reason(key, action):
            return self._say(f"{reason}.")
        if needs_confirm(key, action, from_button=True):
            self._ask_confirm(message, action, "")
        else:
            self._post(message, action, "")

    def _cancelled(self, confirm_id: str) -> None:
        del self.state.messages[confirm_id]
        self._say("Cancelled; nothing was posted.")

    def _confirmed(self, confirm_id: str, message: Message) -> None:
        del self.state.messages[confirm_id]
        if message.action and message.action["kind"] == "start":
            started = self.supervisor.start(message.action["repo"], message.action["idea"])
            return self._say(f"Not started: {started}." if isinstance(started, str) else f"Started {started}.")
        action = action_from(message.action or {})
        if action.kind == "stop":
            return self._say("Stopping; the pipeline posts its cost comment first." if self.supervisor.stop(RunId.parse(message.run)) else "That run is not running.")
        self._post(message, action, message.words)

    def _post(self, message: Message, action: Action, words: str) -> None:
        run = RunId.parse(message.run)
        result = self.poster.post(run, message.bound, action, words)
        if isinstance(result, Refused):
            return self._refused(run, message.bound.key, result.reason)
        self.state.drop_messages(str(run))
        self.state.notified.pop(str(run), None)
        refusal = self.supervisor.resume(run)
        self._say(f"Posted {action.kind} on {run}. {f'Not resumed: {refusal}.' if refusal else 'Resuming.'}")

    def _refused(self, run: RunId, key: str, reason: str) -> None:
        issue: Gateway = self.gateway_for(run)
        comments = issue.comments()
        request = find_request(comments, key)
        current = request and not decision_on(comments, request) and (key != "gate-b" or issue.head() == request.head)
        self.state.drop_messages(str(run))
        if current:
            self._say(f"Nothing posted: {reason}.")
            self._notify(run, request, comments, force=True)
        else:
            self._say(f"Nothing posted: {reason}. Asking the run again.")
            self.state.notified.pop(str(run), None)
            self.supervisor.resume(run)

    def _stop(self, name: str) -> None:
        active = self.supervisor.active()
        if name:
            runs = [run for run in active if str(run) == name]
        else:
            runs = active
        if len(runs) != 1:
            return self._say(f"Say {' or '.join(f'`stop {run}`' for run in active)}." if active else "Nothing is running.")
        message_id = self._send(f"{runs[0]}: stop this run? It is interrupted, posts its cost comment and exits.", CONFIRM_CHOICES)
        self.state.messages[message_id] = Message(str(runs[0]), NO_STAGE, "confirm", asdict(Action("stop")))

    def _undo(self) -> None:
        if not self.state.posted:
            return self._say("I haven't posted anything.")
        run = RunId.parse(self.state.posted[-1][0])
        if run in self.supervisor.active():
            return self._say(f"{run} is still working on that; `stop` it first, then undo.")
        comment_id = self.poster.undo(run)
        self.state.drop_messages(str(run))
        self.state.notified.pop(str(run), None)
        self._say(f"Deleted my comment {comment_id} on {run}. Asking the run again.")
        self.supervisor.resume(run)


def build(home_dir: Path, chat: Chat) -> tuple[Concierge, Supervisor]:
    config = load_config(home_dir / "config.json")
    state = State.load(home_dir / "state.json")
    supervisor = Supervisor(config, state, spawn_local, home_dir / "logs")

    def gateway_for(run: RunId) -> GitHubIssue:
        return GitHubIssue(config.repos[run.repo], run.slug)

    transcriber = CommandTranscriber(config.transcribe_command) if config.transcribe_command else None
    return Concierge(state, supervisor, Poster(state, gateway_for), chat, ClaudeInterpreter(), gateway_for, transcriber), supervisor


def chat_for(config: Config, environ: Mapping[str, str] = os.environ) -> Chat:
    if (token := environ.get(TOKEN_ENV)) and config.telegram_owner_id:
        return TelegramChat(config.telegram_owner_id, bot_http(token), download=bot_download(token))
    return StdinChat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concierge")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="supervise runs and talk to you in Telegram, or in this terminal when it is not set up")
    serve.add_argument("--start", nargs=2, metavar=("REPO", "IDEA"), help="start a run before serving")
    commands.add_parser("eval", help="score the interpreter on its eval cases (spends a little money)")
    args = parser.parse_args(argv)
    if args.command == "eval":
        interpreter = ClaudeInterpreter()
        results = run_cases(lambda case: interpreter.interpret(case.text, case.key, case.questions))
        results += run_start_cases(lambda case: interpreter.start_intent(case.text, case.repos))
        print(render_results(results))
        return int(any(result.failures for result in results))
    app, supervisor = build(home(), chat_for(load_config(home() / "config.json")))
    app.start()
    if args.start and isinstance(started := supervisor.start(*args.start), str):
        print(f"error: {started}", file=sys.stderr)
        return 1
    try:
        while True:
            app.tick()
    except KeyboardInterrupt:
        return 0
