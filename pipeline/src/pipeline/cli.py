import argparse
import os
import sys
import tempfile
from pathlib import Path

from pipeline.agent import AgentError, FakeAgent
from pipeline.claude_agent import ClaudeAgent
from pipeline.cost import DEFAULT_BUDGET_USD, BudgetExceeded, CostLedger
from pipeline.forge import FakeForge, Forge, ForgeError, GitHubForge, RunState, fetch_issue
from pipeline.gates import confirm
from pipeline.run_dir import RunDir, slugify
from pipeline.stages import Pipeline

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
AGENT_TIMEOUT_S = 1800


def dry_run_text(prompt: str) -> str:
    if "/plan/SKILL.md" in prompt:
        return "# Plan\n\n## Phase 1: dry run\n"
    if "/decide/SKILL.md" in prompt:
        return "# Decisions\n\n## Escalated\nNone.\n"
    return "# dry run\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    run = parser.add_subparsers(dest="command", required=True).add_parser("run", help="run the feature pipeline")
    run.add_argument("idea", nargs="?", help="the feature idea")
    run.add_argument("--issue", metavar="REF", help="start from an existing GitHub issue (number or URL)")
    run.add_argument("--resume", metavar="SLUG", help="continue an earlier run")
    run.add_argument("--dry-run", action="store_true", help="use a fake agent and forge in a temp repo")
    run.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    run.add_argument("--stop-after", metavar="STAGE", help="stop once this stage finishes")
    return parser


def run_pipeline(args: argparse.Namespace) -> int:
    repo = Path(tempfile.mkdtemp(prefix="pipeline-dry-run-")) if args.dry_run else args.repo.resolve()
    issue = fetch_issue(repo, args.issue) if args.issue else None
    slug = args.resume or (slugify(f"{issue.number} {issue.title}") if issue else slugify(args.idea))
    run_dir = RunDir(repo, slug)
    state_path = run_dir.path / "state.json"
    if args.resume and not state_path.exists():
        raise ForgeError(f"no run '{slug}' in {repo}")
    if args.resume or (issue and state_path.exists()):
        state = RunState.load(state_path)
    else:
        state = RunState(issue.title, issue.url) if issue else RunState(args.idea)

    forge: Forge = FakeForge() if args.dry_run else GitHubForge(repo, slug, state, state_path)
    forge.start_branch()
    state.save(state_path)
    issue_path = run_dir.artifact_path("issue")
    if issue and not run_dir.exists(issue_path):
        run_dir.write(issue_path, issue.markdown)

    fake_agent = FakeAgent(dry_run_text)
    agent_for = (
        (lambda stage: fake_agent) if args.dry_run
        else (lambda stage: ClaudeAgent(repo, stage.max_turns, AGENT_TIMEOUT_S))
    )
    budget = float(os.environ.get("BUDGET_USD", DEFAULT_BUDGET_USD))
    ledger = CostLedger(run_dir.path / "cost.csv", budget)
    pipeline = Pipeline(
        run_dir, ledger, agent_for, SKILLS_DIR, state.idea,
        (lambda _: True) if args.dry_run else confirm, print, forge, stop_after=args.stop_after,
    )
    stopped = pipeline.run()
    spent = f"spent ${ledger.total():.2f}"
    if stopped is None:
        print(f"Finished in {run_dir.path}; {spent}")
    else:
        print(f"Stopped at '{stopped}'; {spent}. Resume with: pipeline run --resume {slug}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if sum(map(bool, (args.idea, args.resume, args.issue))) != 1:
        parser.error("give exactly one of: an idea, --issue REF, --resume SLUG")
    if args.dry_run and (args.resume or args.issue):
        parser.error("--dry-run cannot resume or use --issue")
    try:
        return run_pipeline(args)
    except (AgentError, BudgetExceeded, ForgeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
