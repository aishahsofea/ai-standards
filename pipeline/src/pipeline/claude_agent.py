import json
import os
import subprocess
import sys
from pathlib import Path

from pipeline.agent import AgentError, Result


class ClaudeAgent:
    def __init__(self, cwd: Path, max_turns: int, timeout_s: float, read_only: bool = False, add_dirs: tuple[Path, ...] = (), node_bin: Path | None = None, allowed_tools: tuple[str, ...] = ()) -> None:
        self.cwd = cwd
        self.max_turns = max_turns
        self.timeout_s = timeout_s
        self.read_only = read_only
        self.add_dirs = add_dirs
        self.node_bin = node_bin
        self.allowed_tools = allowed_tools

    def run(self, prompt: str, model: str, budget: float) -> Result:
        command = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--model", model,
            "--max-turns", str(self.max_turns),
            "--max-budget-usd", str(budget),
        ]
        if self.add_dirs:
            command += ["--add-dir", *map(str, self.add_dirs)]
        if self.allowed_tools:
            command += ["--allowedTools", ",".join(self.allowed_tools)]
        command += ["--disallowedTools", "Edit,Write,NotebookEdit"] if self.read_only else ["--permission-mode", "acceptEdits"]
        try:
            proc = subprocess.run(
                command, cwd=self.cwd, capture_output=True, text=True, timeout=self.timeout_s, env=self._env()
            )
        except subprocess.TimeoutExpired as error:
            raise AgentError(f"claude timed out after {self.timeout_s}s") from error
        if proc.returncode != 0:
            raise AgentError(f"claude exited {proc.returncode}: {proc.stderr.strip()}")
        return self._parse(proc.stdout)

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.node_bin:
            env["PATH"] = f"{self.node_bin}{os.pathsep}{env['PATH']}"
        return env

    @staticmethod
    def _parse(stdout: str) -> Result:
        try:
            payload = json.loads(stdout)
            text, cost = payload["result"], float(payload["total_cost_usd"])
        except (ValueError, KeyError, TypeError) as error:
            raise AgentError(f"unparseable claude output: {stdout[:200]!r}") from error
        if payload.get("is_error"):
            raise AgentError(f"claude reported an error: {text}")
        for denial in payload.get("permission_denials", ()):
            attempted = denial.get("tool_input", {}).get("command", "")
            print(f"claude was denied {denial.get('tool_name')} {attempted!r}; add a rule for it to allowedTools in .pipeline.json", file=sys.stderr)
        return Result(text, cost)
