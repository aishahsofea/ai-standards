import json
from pathlib import Path

CONFIG_FILE = ".pipeline.json"

READ_ONLY_TOOLS = (
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(ls:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(cat:*)",
    "Bash(gh issue view:*)", "Bash(gh issue list:*)", "Bash(gh pr view:*)",
)

RUNNER_TOOLS = (
    "Bash(pytest:*)", "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)",
    "Bash(uv run pytest:*)", "Bash(.venv/bin/pytest:*)", "Bash(.venv/bin/python -m pytest:*)",
    "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(npm run lint:*)", "Bash(npm run build:*)",
    "Bash(npm run typecheck:*)", "Bash(npm --prefix:*)",
    "Bash(npx vitest:*)", "Bash(npx tsc:*)", "Bash(npx eslint:*)", "Bash(npx playwright:*)", "Bash(npx --prefix:*)",
    "Bash(go test:*)", "Bash(go vet:*)", "Bash(cargo test:*)", "Bash(cargo check:*)", "Bash(cargo clippy:*)",
)


def with_rtk(tools: tuple[str, ...]) -> tuple[str, ...]:
    """The user's rtk hook rewrites `pytest` to `rtk pytest` before the permission check."""
    return tools + tuple(tool.replace("Bash(", "Bash(rtk ", 1) for tool in tools if tool.startswith("Bash("))


def repo_tools(repo: Path) -> tuple[str, ...]:
    config = repo / CONFIG_FILE
    if not config.exists():
        return ()
    return tuple(json.loads(config.read_text()).get("allowedTools", ()))


def allowed_tools(repo: Path, read_only: bool) -> tuple[str, ...]:
    return with_rtk(READ_ONLY_TOOLS if read_only else READ_ONLY_TOOLS + RUNNER_TOOLS + repo_tools(repo))
