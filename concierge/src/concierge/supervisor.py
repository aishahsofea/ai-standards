import json
import os
import signal
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from concierge.config import Config
from concierge.state import RunId, RunRecord, State
from pipeline.cost import DEFAULT_BUDGET_USD
from pipeline.run_dir import run_path, slugify

RESUMABLE = {"running", "waiting", "queued", "capped"}
TAIL_CHARS = 8_000


class Process(Protocol):
    def poll(self) -> int | None: ...
    def tail(self) -> str: ...
    def interrupt(self) -> None: ...


class Releasable(Protocol):
    def terminate(self) -> None: ...


Spawn = Callable[[list[str], Path, Path], Process]


@dataclass(frozen=True)
class Outcome:
    run: RunId
    status: str
    stage: str | None = None
    request: str | None = None
    spent_usd: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class Progress:
    run: RunId
    event: str
    stage: str
    detail: str = ""


class LocalProcess:
    def __init__(self, popen: subprocess.Popen, log: Path) -> None:
        self.popen = popen
        self.log = log

    def poll(self) -> int | None:
        return self.popen.poll()

    def tail(self) -> str:
        return self.log.read_text(errors="replace")[-TAIL_CHARS:]

    def interrupt(self) -> None:
        """SIGINT to the whole group, so the pipeline posts its cost comment and its `claude` child exits."""
        os.killpg(self.popen.pid, signal.SIGINT)


def spawn_local(argv: list[str], cwd: Path, log: Path) -> LocalProcess:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as handle:
        popen = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    return LocalProcess(popen, log)


def keep_awake() -> Releasable | None:
    return subprocess.Popen(("caffeinate", "-i")) if sys.platform == "darwin" else None


def run_budget() -> float:
    """The per-run budget the pipeline will use: it reads the same variable from the environment it inherits."""
    return float(os.environ.get("BUDGET_USD", DEFAULT_BUDGET_USD))


def parse_progress(run: RunId, line: bytes) -> Progress | None:
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not (isinstance(data, dict) and isinstance(data.get("event"), str) and isinstance(data.get("stage"), str)):
        return None
    detail = data.get("detail")
    return Progress(run, data["event"], data["stage"], detail if isinstance(detail, str) else "")


def result_line(output: str) -> dict | None:
    for line in reversed(output.strip().splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and "status" in result:
            return result
    return None


class Supervisor:
    def __init__(
        self, config: Config, state: State, spawn: Spawn, logs: Path,
        awake: Callable[[], Releasable | None] = keep_awake, today: Callable[[], str] = lambda: date.today().isoformat(),
    ) -> None:
        self.config = config
        self.state = state
        self.spawn = spawn
        self.logs = logs
        self.awake = awake
        self.today = today
        self.processes: dict[RunId, Process] = {}
        self.queue: deque[RunId] = deque()
        self.jobs: dict[RunId, list[str]] = {}
        self.stopping: set[RunId] = set()
        self._caffeinate: Releasable | None = None

    def check(self, repo: str, idea: str) -> RunId | str:
        """The run `start` would create, or why it would be refused."""
        if repo not in self.config.repos:
            return f"no repo named '{repo}'"
        if idea.lstrip().startswith("-"):
            return "the idea cannot start with '-'"
        try:
            run = RunId(repo, slugify(idea))
        except ValueError as error:
            return str(error)
        if str(run) in self.state.runs or (run_path(self.config.repos[repo], run.slug) / "state.json").exists():
            return f"a run named '{run.slug}' already exists in {repo}"
        return self._cap_refusal() or run

    def start(self, repo: str, idea: str) -> RunId | str:
        run = self.check(repo, idea)
        if isinstance(run, str):
            return run
        return refusal if (refusal := self._submit(run, [idea])) else run

    def resume(self, run: RunId) -> str | None:
        return self._submit(run, ["--resume", run.slug])

    def stop(self, run: RunId) -> bool:
        if run in self.queue:
            self.queue.remove(run)
            del self.jobs[run]
            self.state.runs[str(run)].status = "stopped"
            return True
        if run not in self.processes or run in self.stopping:
            return False
        self.stopping.add(run)
        self.processes[run].interrupt()
        return True

    def active(self) -> list[RunId]:
        return [*self.processes, *self.queue]

    def spent_today(self) -> float:
        return self.state.spend.get(self.today(), 0.0)

    def remaining_today(self) -> float:
        return max(0.0, self.config.daily_cap_usd - self.spent_today())

    def add_spend(self, usd: float) -> None:
        self.state.spend[self.today()] = self.spent_today() + usd

    def recover(self) -> list[Outcome]:
        """Resumes every known run that is not running; with no new reply a resume only re-asks, so this is the whole recovery path."""
        outcomes = []
        for name, record in list(self.state.runs.items()):
            if record.status in RESUMABLE and (reason := self.resume(RunId.parse(name))):
                outcomes.append(Outcome(RunId.parse(name), "capped", detail=reason))
        return outcomes

    def poll(self) -> list[Outcome | Progress]:
        """Progress read from each run's event log comes before the run's own outcome."""
        updates: list[Outcome | Progress] = []
        for run, process in list(self.processes.items()):
            code = process.poll()
            updates += self._progress(run)
            if code is not None:
                updates.append(self._finish(run, code))
        updates += self._pump()
        if not self.processes and self._caffeinate:
            self._caffeinate.terminate()
            self._caffeinate = None
        return updates

    def events_path(self, run: RunId) -> Path:
        return self.logs / f"{run.repo}-{run.slug}.events.jsonl"

    def _progress(self, run: RunId) -> list[Progress]:
        """Reads only complete lines after the saved byte offset, so a half-written last line waits for its newline."""
        record = self.state.runs[str(run)]
        try:
            with self.events_path(run).open("rb") as events:
                events.seek(record.events_offset)
                data = events.read()
        except FileNotFoundError:
            return []
        complete = data[: data.rfind(b"\n") + 1]
        record.events_offset += len(complete)
        return [progress for line in complete.splitlines() if (progress := parse_progress(run, line))]

    def _cap_refusal(self) -> str | None:
        if self.spent_today() >= self.config.daily_cap_usd:
            return f"the daily spend cap of ${self.config.daily_cap_usd:.2f} is reached (${self.spent_today():.2f} spent)"
        return None

    def _submit(self, run: RunId, tail: list[str]) -> str | None:
        if run in self.processes or run in self.queue:
            return f"'{run}' is already running"
        if refusal := self._cap_refusal():
            return refusal
        self.state.runs.setdefault(str(run), RunRecord())
        self.jobs[run] = tail
        self.queue.append(run)
        self.state.runs[str(run)].status = "queued"
        self._pump()
        return None

    def _pump(self) -> list[Outcome]:
        outcomes = []
        while self.queue and len(self.processes) < self.config.max_concurrent:
            run = self.queue.popleft()
            if self.spent_today() >= self.config.daily_cap_usd:
                del self.jobs[run]
                self.state.runs[str(run)].status = "capped"
                outcomes.append(Outcome(run, "capped", detail=f"the daily spend cap of ${self.config.daily_cap_usd:.2f} is reached"))
                continue
            self._launch(run)
        return outcomes

    def _launch(self, run: RunId) -> None:
        repo = self.config.repos[run.repo]
        tail = self.jobs.pop(run)
        argv = [*self.config.pipeline_command, "run", *tail, "--repo", str(repo), "--headless", "--worktree", "--json", "--events", str(self.events_path(run))]
        self.processes[run] = self.spawn(argv, repo, self.logs / f"{run.repo}-{run.slug}.log")
        self.state.runs[str(run)].status = "running"
        if self._caffeinate is None:
            self._caffeinate = self.awake()

    def _finish(self, run: RunId, code: int) -> Outcome:
        output = self.processes.pop(run).tail()
        record = self.state.runs[str(run)]
        result = result_line(output)
        spent = 0.0
        if result:
            total = float(result.get("spent_usd", 0.0))
            spent, record.spent_usd = max(0.0, total - record.spent_usd), total
            self.add_spend(spent)
        if run in self.stopping:
            self.stopping.discard(run)
            outcome = Outcome(run, "stopped", spent_usd=spent, detail="stopped by you")
        elif result and code in (0, 3):
            outcome = Outcome(run, result["status"], result.get("stage"), result.get("request"), spent)
        else:
            lines = [line for line in output.splitlines() if line.strip()]
            outcome = Outcome(run, "error", spent_usd=spent, detail=lines[-1] if lines else f"exited {code}")
        record.status, record.request = outcome.status, outcome.request or ""
        return outcome
