import argparse
import os
import sys
import tempfile
from pathlib import Path

from pipeline.agent import AgentError, FakeAgent
from pipeline.claude_agent import ClaudeAgent
from pipeline.cost import DEFAULT_BUDGET_USD, BudgetExceeded, CostLedger, prior_total, render_table
from pipeline.evals import render_results, run_evals
from pipeline.forge import FakeForge, Forge, ForgeError, GitHubForge, RunState, fetch_issue
from pipeline.gates import GateError, confirm
from pipeline.node_bin import NodeNotFound, resolve_node_bin
from pipeline.permissions import allowed_tools
from pipeline.run_dir import RunDir, slugify
from pipeline.stages import Pipeline

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
AGENT_TIMEOUT_S = 1800


def dry_run_text(prompt: str) -> str:
    if "/plan/SKILL.md" in prompt:
        return "# Plan\n\n## Phase 1: dry run\n"
    if "/decide/SKILL.md" in prompt:
        return "# Decisions\n\n## Decided from evidence\nNone.\n\n## Decided, low stakes\nNone.\n\n## Escalated\nNone.\n"
    if "/analyze/SKILL.md" in prompt:
        return "# Analysis\n\n## Open questions\nNone.\n"
    if "/implement-phase/SKILL.md" in prompt:
        return "Status: done\n# dry run\n"
    if "/test/SKILL.md" in prompt or "/review/SKILL.md" in prompt:
        return "Status: pass\n# dry run\n"
    return "# dry run\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    evals = commands.add_parser("eval", help="score the decide and plan skills on fixture cases (spends money)")
    evals.add_argument("--case", action="append", default=[], metavar="NAME", help="only this case (repeatable)")
    run = commands.add_parser("run", help="run the feature pipeline")
    run.add_argument("idea", nargs="?", help="the feature idea")
    run.add_argument("--issue", metavar="REF", help="start from an existing GitHub issue (number or URL)")
    run.add_argument("--resume", metavar="SLUG", help="continue an earlier run")
    run.add_argument("--dry-run", action="store_true", help="use a fake agent and forge in a temp repo")
    run.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    run.add_argument("--stop-after", metavar="STAGE", help="stop once this stage finishes")
    return parser


def post_cost(forge: Forge, ledger: CostLedger) -> None:
    table = render_table(ledger)
    try:
        forge.post_artifact("cost", table)
    except (ForgeError, OSError) as error:
        print(f"could not post the cost comment: {error}\n{table}", file=sys.stderr)


def run_pipeline(args: argparse.Namespace) -> int:
    repo = Path(tempfile.mkdtemp(prefix="pipeline-dry-run-")) if args.dry_run else args.repo.resolve()
    node_bin = None if args.dry_run else resolve_node_bin(repo)
    issue = fetch_issue(repo, args.issue) if args.issue else None
    slug = args.resume or (slugify(f"{issue.number} {issue.title}") if issue else slugify(args.idea))
    run_dir = RunDir(repo, slug)
    state_path = run_dir.state_path
    if args.resume and not state_path.exists():
        raise ForgeError(f"no run '{slug}' in {repo}")
    if args.resume or (issue and state_path.exists()):
        state = RunState.load(state_path)
    else:
        state = RunState(issue.title, issue.url) if issue else RunState(args.idea)

    forge: Forge = FakeForge() if args.dry_run else GitHubForge(repo, slug, state, state_path)
    forge.start_branch()
    state.save(state_path)

    fake_agent = FakeAgent(dry_run_text)
    agent_for = (
        (lambda stage: fake_agent) if args.dry_run
        else (lambda stage: ClaudeAgent(repo, stage.max_turns, AGENT_TIMEOUT_S, stage.read_only, (SKILLS_DIR, run_dir.staging), node_bin, allowed_tools(repo, stage.read_only)))
    )
    budget = float(os.environ.get("BUDGET_USD", DEFAULT_BUDGET_USD))
    ledger = CostLedger(budget, prior_total(forge.read_artifact("cost")))
    pipeline = Pipeline(
        run_dir, ledger, agent_for, SKILLS_DIR, state.idea,
        (lambda _: True) if args.dry_run else confirm, print, forge, stop_after=args.stop_after,
        ask=None if args.dry_run else input,
    )
    try:
        stopped = pipeline.run()
    finally:
        post_cost(forge, ledger)
        run_dir.close()
    spent = f"spent ${ledger.total():.2f}"
    if stopped is None:
        print(f"Finished; {spent}")
    else:
        print(f"Stopped at '{stopped}'; {spent}. Resume with: pipeline run --resume {slug}")
    return 0


def run_eval(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="pipeline-eval-") as workdir:
        results = run_evals(
            args.case, lambda staging: ClaudeAgent(Path(workdir), 30, AGENT_TIMEOUT_S, True, (SKILLS_DIR, staging)),
            SKILLS_DIR, Path(workdir),
        )
    print(render_results(results))
    return int(any(result.failures for result in results))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "eval":
        try:
            return run_eval(args)
        except AgentError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    if sum(map(bool, (args.idea, args.resume, args.issue))) != 1:
        parser.error("give exactly one of: an idea, --issue REF, --resume SLUG")
    if args.dry_run and (args.resume or args.issue):
        parser.error("--dry-run cannot resume or use --issue")
    try:
        return run_pipeline(args)
    except (AgentError, BudgetExceeded, ForgeError, GateError, NodeNotFound) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
