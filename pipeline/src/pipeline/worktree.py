import shutil
from pathlib import Path

from pipeline.checks import CHECK_TIMEOUT_S, run_check
from pipeline.forge import ForgeError, branch_name, run_command
from pipeline.permissions import repo_setting

WORKTREES_DIR = Path.home() / ".pipeline" / "worktrees"


def create_worktree(repo: Path, slug: str, env: dict[str, str], root: Path = WORKTREES_DIR) -> Path:
    """Adds a worktree on a new run branch, copies in the files the repo lists under "copy" and runs its "setup" commands."""
    path = root / repo.name / slug
    run_command(("git", "worktree", "add", str(path), "-b", branch_name(slug)), repo)
    try:
        prepare(repo, path, env)
    except (ForgeError, OSError):
        run_command(("git", "worktree", "remove", "--force", str(path)), repo)
        run_command(("git", "branch", "-D", branch_name(slug)), repo)
        raise
    return path


def prepare(repo: Path, path: Path, env: dict[str, str]) -> None:
    for name in repo_setting(repo, "copy"):
        source, target = repo / name, path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    for command in repo_setting(repo, "setup"):
        run = run_check(command, path, env, CHECK_TIMEOUT_S)
        if not run.ok:
            raise ForgeError(f"setup command `{command}` failed:\n{run.tail}")
