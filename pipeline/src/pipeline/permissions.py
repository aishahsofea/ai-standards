import json
from collections.abc import Callable
from pathlib import Path

from pipeline.agent import Denial

CONFIG_FILE = ".pipeline.json"

READ_ONLY_TOOLS = (
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(ls:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(cat:*)", "Bash(wc:*)",
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


def save_repo_rule(repo: Path, rule: str) -> None:
    config = repo / CONFIG_FILE
    data = json.loads(config.read_text()) if config.exists() else {}
    if rule not in data.get("allowedTools", ()):
        data["allowedTools"] = [*data.get("allowedTools", ()), rule]
        config.write_text(json.dumps(data, indent=2) + "\n")


def ask_approvals(
    denials: tuple[Denial, ...], ask: Callable[[str], str], repo: Path, declined: set[str]
) -> list[str]:
    """Asks about each distinct denied rule; returns the ones allowed, saving 'a' answers to .pipeline.json."""
    approved: list[str] = []
    for denial in {d.rule: d for d in denials if d.rule not in declined}.values():
        reply = ask(f"Agent was denied `{denial.command or denial.tool}`. Allow {denial.rule}? (y this run, a always, Enter skip): ").strip().lower()
        if reply in ("y", "a"):
            approved.append(denial.rule)
            if reply == "a":
                save_repo_rule(repo, denial.rule)
        else:
            declined.add(denial.rule)
    return approved
