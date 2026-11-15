import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pipeline.agent import AgentError, Denial, FakeAgent
from pipeline.checks import run_checks
from pipeline.claude_agent import ClaudeAgent
from pipeline.cost import DEFAULT_BUDGET_USD, BudgetExceeded, CostLedger, prior_total, render_table
from pipeline.evals import render_results, run_evals, run_review_evals
from pipeline.forge import FakeForge, Forge, ForgeError, GitHubForge, RunState, fetch_issue, pipeline_issues, request_name
from pipeline.gates import GateError, confirm, plan_commands
from pipeline.node_bin import NodeNotFound, env_with_node, resolve_node_bin
from pipeline.owner import HeadlessOwner, Owner, TerminalOwner
from pipeline.permissions import allowed_tools, ask_approvals, command_rules, repo_checks
from pipeline.run_dir import RunDir, RunLocked, run_lock, slugify
from pipeline.stages import CI_TIMEOUT_S, PLAN, Pipeline, Stage
from pipeline.stats import render_stats, run_stats
from pipeline.worktree import create_worktree

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
AGENT_TIMEOUT_S = 1800
EVIDENCE_ENV = "PIPELINE_EVIDENCE_DIR"
HEADLESS_HELP = "never read the terminal: ask on the issue and exit 3 while waiting for a reply"
JSON_HELP = "print a final line of JSON: status (finished, stopped or waiting), stage, request and spent_usd"
EVENTS_HELP = "append one JSON line per progress event (stage-started, stage-finished, plan-posted, ci-green, blocked) to this file"
EVENT_DETAIL_CHARS = 120
WAITING_EXIT = 3


def dry_run_text(prompt: str) -> str:
    if "/plan/SKILL.md" in prompt:
        return "# Plan\n\n## Phase 1: dry run\n- Verify: pytest\n\n## Acceptance criteria\n- it runs: Phase 1\n"
    if "/decide/SKILL.md" in prompt:
        return "# Decisions\n\n## Decided from evidence\nNone.\n\n## Decided, low stakes\nNone.\n\n## Escalated\nNone.\n"
    if "/analyze/SKILL.md" in prompt:
        return "# Analysis\n\n## Open questions\nNone.\n"
    if "/implement-phase/SKILL.md" in prompt:
        return "Status: done\n# dry run\n"
    if "/test/SKILL.md" in prompt or "/review/SKILL.md" in prompt:
        return "Status: pass\n# dry run\n"
    return "# dry run\n"


def notify(message: str) -> None:
    print("\a", end="", flush=True)
    if sys.platform == "darwin":
        script = f'display notification {json.dumps(message)} with title "pipeline"'
        subprocess.run(("osascript", "-e", script), capture_output=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    evals = commands.add_parser("eval", help="score the decide and plan, or review, skills on fixture cases (spends money)")
    evals.add_argument("--case", action="append", default=[], metavar="NAME", help="only this case (repeatable)")
    evals.add_argument("--suite", choices=("decide", "review"), default="decide", help="decide scores decide and plan (default)")
    run = commands.add_parser("run", help="run the feature pipeline")
    run.add_argument("idea", nargs="?", help="the feature idea")
    run.add_argument("--issue", metavar="REF", help="start from an existing GitHub issue (number or URL)")
    run.add_argument("--resume", metavar="SLUG", help="continue an earlier run")
    run.add_argument("--dry-run", action="store_true", help="use a fake agent and forge in a temp repo")
    run.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    run.add_argument("--stop-after", metavar="STAGE", help="stop once this stage finishes")
    run.add_argument("--worktree", action="store_true", help="work in a separate git worktree and leave this checkout alone")
    run.add_argument("--step", action="store_true", help="ask y/N after every stage, not only at the gates and the plan")
    run.add_argument("--headless", action="store_true", help=HEADLESS_HELP)
    run.add_argument("--json", action="store_true", help=JSON_HELP)
    run.add_argument("--events", type=Path, metavar="PATH", help=EVENTS_HELP)
    revise = commands.add_parser("revise", help="apply your feedback to a finished run's branch")
    revise.add_argument("slug", help="the run to revise")
    revise.add_argument("feedback", help="what should change")
    revise.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    revise.add_argument("--headless", action="store_true", help=HEADLESS_HELP)
    revise.add_argument("--json", action="store_true", help=JSON_HELP)
    revise.add_argument("--events", type=Path, metavar="PATH", help=EVENTS_HELP)
    revise.set_defaults(dry_run=False)
    stats = commands.add_parser("stats", help="show where past runs in a repo stopped and what they cost")
    stats.add_argument("--repo", type=Path, default=Path.cwd(), help="target repo (default: current directory)")
    return parser


def event_writer(path: Path | None) -> Callable[[str, str, str], None]:
    def emit(event: str, stage: str, detail: str) -> None:
        if path is None:
            return
        line = {"event": event, "stage": stage, "detail": detail[:EVENT_DETAIL_CHARS], "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            with path.open("a") as events:
                events.write(json.dumps(line) + "\n")
        except OSError:
            pass  # progress is informational; a bad path must not stop a paid run

    return emit


def post_cost(forge: Forge, ledger: CostLedger) -> None:
    table = render_table(ledger)
    try:
        forge.post_artifact("cost", table)
    except (ForgeError, OSError) as error:
        print(f"could not post the cost comment: {error}\n{table}", file=sys.stderr)


def open_run(args: argparse.Namespace, repo: Path, slug: str, state: RunState) -> tuple[Pipeline, RunDir, Forge, CostLedger]:
    state_path = RunDir(repo, slug).state_path
    node_bin = None if args.dry_run else resolve_node_bin(repo)
    if getattr(args, "worktree", False) and not state.worktree:
        state.worktree = str(create_worktree(repo, slug, env_with_node(node_bin)))
        state.save(state_path)
    work = Path(state.worktree) if state.worktree else repo
    if not work.is_dir():
        raise ForgeError(f"the run's worktree {work} is missing")
    if state.worktree:
        print(f"Working in {work}")
    run_dir = RunDir(repo, slug, work)
    forge: Forge = FakeForge() if args.dry_run else GitHubForge(work, slug, state, state_path)
    forge.start_branch()
    state.save(state_path)

    fake_agent = FakeAgent(dry_run_text)
    approved: list[str] = []
    declined: set[str] = set()

    def approve_denials(denials: tuple[Denial, ...]) -> bool:
        allowed = ask_approvals(denials, input, repo, declined)
        approved.extend(allowed)
        return bool(allowed)

    def tools(stage: Stage) -> tuple[str, ...]:
        """A stage that reads the plan only runs after the owner approved it, and its commands with it."""
        follows_plan = PLAN.output in stage.inputs and not stage.read_only
        plan = forge.read_artifact(PLAN.output) or "" if follows_plan else ""
        return (*allowed_tools(repo, stage.read_only), *approved, *command_rules(plan_commands(plan)))

    agent_for = (
        (lambda stage: fake_agent) if args.dry_run
        else (lambda stage: ClaudeAgent(work, stage.max_turns, AGENT_TIMEOUT_S, stage.read_only, (SKILLS_DIR, run_dir.staging), node_bin, tools(stage), {EVIDENCE_ENV: str(run_dir.evidence)}))
    )
    commands = () if args.dry_run else repo_checks(repo)
    if not (commands or args.dry_run):
        print('No preflight: list the check commands under "checks" in .pipeline.json to run them before any change.', file=sys.stderr)
    budget = float(os.environ.get("BUDGET_USD", DEFAULT_BUDGET_USD))
    ledger = CostLedger(budget, prior_total(forge.read_artifact("cost")))
    owner: Owner
    if args.headless:
        owner = HeadlessOwner(forge, approved)
    elif args.dry_run:
        owner = TerminalOwner(lambda _: True)
    else:
        owner = TerminalOwner(confirm, input, approve_denials, notify)
    pipeline = Pipeline(
        run_dir, ledger, agent_for, SKILLS_DIR, state.idea, owner, print, forge,
        stop_after=getattr(args, "stop_after", None), pause_each=getattr(args, "step", False),
        checks=(lambda: run_checks(commands, work, env_with_node(node_bin))) if commands else None,
        ci_timeout_s=float(os.environ.get("CI_TIMEOUT_S", CI_TIMEOUT_S)),
        emit=event_writer(args.events),
    )
    return pipeline, run_dir, forge, ledger


def finish_run(
    pipeline: Pipeline, pipeline_run: Callable[[], str | None], run_dir: RunDir, forge: Forge, ledger: CostLedger, slug: str, as_json: bool = False
) -> int:
    try:
        stopped = pipeline_run()
    finally:
        post_cost(forge, ledger)
        run_dir.close()
    spent = f"spent ${ledger.total():.2f}"
    waiting = pipeline.owner.waiting
    if stopped is None:
        print(f"Finished; {spent}")
    elif waiting:
        print(
            f"Waiting on the owner at '{stopped}'; {spent}. Reply to the '{request_name(waiting)}' comment on the issue, "
            f"then run: pipeline run --resume {slug} --headless"
        )
    else:
        print(f"Stopped at '{stopped}'; {spent}. Resume with: pipeline run --resume {slug}")
        if stopped != pipeline.stop_after:
            pipeline.emit("blocked", stopped, f"stopped at {stopped}")
        pipeline.owner.notify(f"{slug} stopped at {stopped}")
    if as_json:
        status = "finished" if stopped is None else "waiting" if waiting else "stopped"
        print(json.dumps({"status": status, "stage": stopped, "request": waiting if stopped else None, "spent_usd": round(ledger.total(), 4)}))
    return WAITING_EXIT if stopped and waiting else 0


def run_pipeline(args: argparse.Namespace) -> int:
    repo = Path(tempfile.mkdtemp(prefix="pipeline-dry-run-")) if args.dry_run else args.repo.resolve()
    issue = fetch_issue(repo, args.issue) if args.issue else None
    slug = args.resume or (slugify(f"{issue.number} {issue.title}") if issue else slugify(args.idea))
    with run_lock(repo, slug):
        state_path = RunDir(repo, slug).state_path
        if args.resume and not state_path.exists():
            raise ForgeError(f"no run '{slug}' in {repo}")
        if args.resume or (issue and state_path.exists()):
            state = RunState.load(state_path)
        else:
            state = RunState(issue.title, issue.url) if issue else RunState(args.idea)
        pipeline, run_dir, forge, ledger = open_run(args, repo, slug, state)
        return finish_run(pipeline, pipeline.run, run_dir, forge, ledger, slug, args.json)


def revise_pipeline(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    with run_lock(repo, args.slug):
        state_path = RunDir(repo, args.slug).state_path
        if not state_path.exists():
            raise ForgeError(f"no run '{args.slug}' in {repo}")
        pipeline, run_dir, forge, ledger = open_run(args, repo, args.slug, RunState.load(state_path))
        return finish_run(pipeline, lambda: pipeline.revise(args.feedback), run_dir, forge, ledger, args.slug, args.json)


def run_eval(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="pipeline-eval-") as workdir:
        if args.suite == "review":
            results = run_review_evals(
                args.case,
                lambda repo, staging: ClaudeAgent(repo, 30, AGENT_TIMEOUT_S, True, (SKILLS_DIR, staging), allowed_tools=allowed_tools(repo, True)),
                SKILLS_DIR, Path(workdir),
            )
        else:
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
    if args.command == "run":
        if sum(map(bool, (args.idea, args.resume, args.issue))) != 1:
            parser.error("give exactly one of: an idea, --issue REF, --resume SLUG")
        if args.dry_run and (args.resume or args.issue or args.worktree):
            parser.error("--dry-run cannot resume or use --issue or --worktree")
        if args.headless and args.step:
            parser.error("--headless cannot be used with --step")
    try:
        if args.command == "stats":
            print(render_stats([run_stats(issue) for issue in pipeline_issues(args.repo.resolve())]))
            return 0
        return run_pipeline(args) if args.command == "run" else revise_pipeline(args)
    except (AgentError, BudgetExceeded, ForgeError, GateError, NodeNotFound, RunLocked) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
