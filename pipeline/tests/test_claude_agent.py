import json
import subprocess

import pytest

from pipeline.agent import AgentError, FakeAgent
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
