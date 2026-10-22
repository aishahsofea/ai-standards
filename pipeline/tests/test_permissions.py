from pipeline.permissions import READ_ONLY_TOOLS, RUNNER_TOOLS, allowed_tools, with_rtk


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
