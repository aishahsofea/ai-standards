import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

CHECK_TIMEOUT_S = 1800
TAIL_CHARS = 3000


@dataclass(frozen=True)
class CheckRun:
    command: str
    ok: bool
    tail: str = ""


def run_checks(commands: tuple[str, ...], cwd: Path, env: dict[str, str], timeout_s: float = CHECK_TIMEOUT_S) -> list[CheckRun]:
    return [run_check(command, cwd, env, timeout_s) for command in commands]


def run_check(command: str, cwd: Path, env: dict[str, str], timeout_s: float) -> CheckRun:
    try:
        proc = subprocess.run(shlex.split(command), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckRun(command, False, str(error))
    return CheckRun(command, proc.returncode == 0, (proc.stdout + proc.stderr)[-TAIL_CHARS:].strip())


def baseline_report(runs: list[CheckRun]) -> str:
    failing = [run for run in runs if not run.ok]
    if not failing:
        return "Every check passed before this branch changed anything: " + ", ".join(f"`{run.command}`" for run in runs) + "."
    sections = [f"### `{run.command}`\n\n```\n{run.tail}\n```" for run in failing]
    return "\n\n".join(["These checks failed before this branch changed anything, so the failures below are not this branch's fault.", *sections])
