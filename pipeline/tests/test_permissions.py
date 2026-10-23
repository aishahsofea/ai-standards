import json

import pytest

from pipeline.agent import Denial
from pipeline.permissions import READ_ONLY_TOOLS, RUNNER_TOOLS, allowed_tools, ask_approvals, with_rtk


def test_read_only_stages_get_no_runners(tmp_path):
    assert allowed_tools(tmp_path, read_only=True) == with_rtk(READ_ONLY_TOOLS)


def test_writing_stages_get_runners_and_no_git_writes(tmp_path):
    tools = allowed_tools(tmp_path, read_only=False)
    assert set(RUNNER_TOOLS) <= set(tools)
    assert not [tool for tool in tools if "git commit" in tool or "git push" in tool]


def test_repo_config_extends_writing_stages_only(tmp_path):
    (tmp_path / ".pipeline.json").write_text('{"allowedTools": ["Bash(make check:*)"]}')
    assert "Bash(make check:*)" in allowed_tools(tmp_path, read_only=False)
    assert "Bash(make check:*)" not in allowed_tools(tmp_path, read_only=True)


def test_rtk_prefixed_variants_are_allowed(tmp_path):
    tools = allowed_tools(tmp_path, read_only=False)
    assert {"Bash(pytest:*)", "Bash(rtk pytest:*)", "Bash(rtk git diff:*)"} <= set(tools)


@pytest.mark.parametrize(
    "denial, rule",
    [
        (Denial("Bash", "git stash"), "Bash(git stash:*)"),
        (Denial("Bash", "initdb -D /tmp/pg"), "Bash(initdb:*)"),
        (Denial("Bash", "docker run --rm postgres"), "Bash(docker run:*)"),
        (Denial("WebFetch"), "WebFetch"),
    ],
)
def test_denial_rule(denial, rule):
    assert denial.rule == rule


def answers(*replies):
    queue = iter(replies)
    return lambda _: next(queue)


def test_approvals_allow_once_save_always_and_remember_declines(tmp_path):
    denials = (Denial("Bash", "docker ps"), Denial("Bash", "docker ps -a"), Denial("Bash", "initdb -D x"), Denial("Bash", "git stash"))
    declined: set[str] = set()
    assert ask_approvals(denials, answers("y", "a", ""), tmp_path, declined) == ["Bash(docker ps:*)", "Bash(initdb:*)"]
    assert json.loads((tmp_path / ".pipeline.json").read_text()) == {"allowedTools": ["Bash(initdb:*)"]}
    assert declined == {"Bash(git stash:*)"}
    assert ask_approvals(denials[3:], answers(), tmp_path, declined) == []
