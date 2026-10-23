import json
import subprocess
from pathlib import Path

import pytest

from pipeline.agent import AgentError, Denial, FakeAgent
from pipeline.claude_agent import ClaudeAgent


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def payload(**overrides):
    return json.dumps({"result": "done", "total_cost_usd": 0.42, "is_error": False, **overrides})


@pytest.fixture
def agent(tmp_path):
    return ClaudeAgent(tmp_path, max_turns=7, timeout_s=30)


def test_parses_text_and_cost(agent, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(payload()))
    result = agent.run("hi", "sonnet", 2.0)
    assert (result.text, result.cost_usd) == ("done", 0.42)


def test_builds_command_and_passes_limits(agent, monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return completed(payload())

    monkeypatch.setattr(subprocess, "run", fake_run)
    agent.run("hi", "opus", 3.5)
    command = seen["command"]
    assert command[:3] == ["claude", "-p", "hi"]
    assert command[command.index("--model") + 1] == "opus"
    assert command[command.index("--max-turns") + 1] == "7"
    assert command[command.index("--max-budget-usd") + 1] == "3.5"
    assert command[command.index("--output-format") + 1] == "json"
    assert seen["timeout"] == 30
    assert seen["cwd"] == tmp_path


def test_non_zero_exit_raises(agent, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(returncode=2, stderr="boom"))
    with pytest.raises(AgentError, match="boom"):
        agent.run("hi", "sonnet", 1)


def test_timeout_raises(agent, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("claude", 30)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(AgentError, match="timed out"):
        agent.run("hi", "sonnet", 1)


def test_error_result_raises(agent, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: completed(payload(is_error=True, result="auth failed"))
    )
    with pytest.raises(AgentError, match="auth failed"):
        agent.run("hi", "sonnet", 1)


@pytest.mark.parametrize("stdout", ["not json", "{}", json.dumps({"result": "x"})])
def test_malformed_output_raises(agent, monkeypatch, stdout):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(stdout))
    with pytest.raises(AgentError, match="unparseable"):
        agent.run("hi", "sonnet", 1)


def test_fake_agent_records_calls():
    fake = FakeAgent(lambda prompt: prompt.upper(), cost_usd=0.1)
    result = fake.run("abc", "haiku", 1.0)
    assert (result.text, result.cost_usd) == ("ABC", 0.1)
    assert fake.calls == [("abc", "haiku", 1.0)]


def test_runs_in_auto_mode_and_never_commits_or_pushes(agent, monkeypatch):
    monkeypatch.delenv("PIPELINE_PERMISSION_MODE", raising=False)
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(command=command) or completed(payload()))
    agent.run("hi", "sonnet", 1.0)
    command = seen["command"]
    assert command[command.index("--permission-mode") + 1] == "auto"
    assert command[command.index("--disallowedTools") + 1] == "Bash(git commit:*),Bash(git push:*)"


def test_permission_mode_can_fall_back_to_accept_edits(agent, monkeypatch):
    monkeypatch.setenv("PIPELINE_PERMISSION_MODE", "acceptEdits")
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(command=command) or completed(payload()))
    agent.run("hi", "sonnet", 1.0)
    command = seen["command"]
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"


def test_read_only_also_denies_edit_tools(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(command=command) or completed(payload()))
    ClaudeAgent(tmp_path, 7, 30, read_only=True).run("hi", "opus", 1.0)
    command = seen["command"]
    assert command[command.index("--disallowedTools") + 1] == "Edit,Write,NotebookEdit,Bash(git commit:*),Bash(git push:*)"


def test_add_dirs_are_passed_for_reading_outside_the_repo(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(command=command) or completed(payload()))
    ClaudeAgent(tmp_path, 7, 30, False, (Path("/skills"), Path("/inputs"))).run("hi", "opus", 1.0)
    command = seen["command"]
    start = command.index("--add-dir")
    assert command[start + 1 : start + 3] == ["/skills", "/inputs"]


def test_allowed_tools_are_passed_comma_joined(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(command=command) or completed(payload()))
    ClaudeAgent(tmp_path, 7, 30, allowed_tools=("Bash(a:*)", "Bash(b:*)")).run("hi", "opus", 1.0)
    command = seen["command"]
    assert command[command.index("--allowedTools") + 1] == "Bash(a:*),Bash(b:*)"


def test_no_allowed_tools_flag_by_default(agent, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(command=command) or completed(payload()))
    agent.run("hi", "opus", 1.0)
    assert "--allowedTools" not in seen["command"]


def test_permission_denials_are_reported_with_the_fix(agent, monkeypatch, capsys):
    denials = [{"tool_name": "Bash", "tool_input": {"command": "make check"}}]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(payload(permission_denials=denials)))
    agent.run("hi", "opus", 1.0)
    err = capsys.readouterr().err
    assert "make check" in err and ".pipeline.json" in err
    assert agent.run("hi", "opus", 1.0).denials == (Denial("Bash", "make check"),)


def test_node_bin_leads_path(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(k) or completed(payload()))
    monkeypatch.setenv("PATH", "/usr/bin")
    ClaudeAgent(tmp_path, 7, 30, node_bin=Path("/node22/bin")).run("hi", "opus", 1.0)
    assert seen["env"]["PATH"] == "/node22/bin:/usr/bin"


def test_path_is_untouched_without_node_bin(agent, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **k: seen.update(k) or completed(payload()))
    monkeypatch.setenv("PATH", "/usr/bin")
    agent.run("hi", "opus", 1.0)
    assert seen["env"]["PATH"] == "/usr/bin"
