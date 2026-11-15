from pathlib import Path

import pytest

from concierge.config import Config
from concierge.state import RunId, State
from concierge.supervisor import Outcome, Progress, Supervisor, run_budget
from fakes import FakeCaffeinate, FakeSpawn
from pipeline.cost import DEFAULT_BUDGET_USD

RUN = RunId("shop", "add-dark-mode")


@pytest.fixture
def world(tmp_path):
    repo = tmp_path / "shop"
    repo.mkdir()
    config = Config({"shop": repo, "blog": tmp_path / "blog"}, max_concurrent=2, daily_cap_usd=10.0, pipeline_command=("pipeline",))
    spawn, caffeinate = FakeSpawn(), FakeCaffeinate()
    state = State(tmp_path / "state.json")
    supervisor = Supervisor(config, state, spawn, tmp_path / "logs", caffeinate, lambda: "2026-11-14")
    return supervisor, spawn, caffeinate, state, repo


def test_a_new_run_is_headless_in_a_worktree_with_a_json_result(world, tmp_path):
    supervisor, spawn, _, _, repo = world
    assert supervisor.start("shop", "Add dark mode") == RUN
    assert spawn.processes[0].argv == ["pipeline", "run", "Add dark mode", "--repo", str(repo), "--headless", "--worktree", "--json", "--events", str(tmp_path / "logs" / "shop-add-dark-mode.events.jsonl")]
    assert spawn.cwds == [repo]


def test_a_resume_names_the_slug(world, tmp_path):
    supervisor, spawn, _, _, repo = world
    assert supervisor.resume(RUN) is None
    assert spawn.processes[0].argv == [
        "pipeline", "run", "--resume", "add-dark-mode", "--repo", str(repo), "--headless", "--worktree", "--json",
        "--events", str(tmp_path / "logs" / "shop-add-dark-mode.events.jsonl"),
    ]


def test_an_unknown_repo_or_an_existing_slug_is_refused(world):
    supervisor, spawn, _, _, repo = world
    assert "no repo named 'nope'" in supervisor.start("nope", "x")
    (repo / ".agent" / "runs" / "add-dark-mode").mkdir(parents=True)
    (repo / ".agent" / "runs" / "add-dark-mode" / "state.json").write_text("{}")
    assert "already exists" in supervisor.start("shop", "Add dark mode")
    assert spawn.processes == []


def test_a_run_already_going_is_not_started_twice(world):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    assert "already running" in supervisor.resume(RUN)
    assert len(spawn.processes) == 1


def test_a_wait_reports_the_stage_the_request_and_the_new_spend(world):
    supervisor, spawn, _, state, _ = world
    supervisor.resume(RUN)
    assert supervisor.poll() == []
    spawn.processes[0].exit(3, status="waiting", stage="plan", request="plan", spent_usd=1.5)
    assert supervisor.poll() == [Outcome(RUN, "waiting", "plan", "plan", 1.5)]
    assert state.runs[str(RUN)].status == "waiting" and state.runs[str(RUN)].request == "plan"
    assert supervisor.spent_today() == 1.5


def test_spend_counts_only_what_a_resume_added(world):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    spawn.processes[0].exit(3, status="waiting", stage="plan", request="plan", spent_usd=1.5)
    supervisor.poll()
    supervisor.resume(RUN)
    spawn.processes[1].exit(3, status="waiting", stage="docs", request="gate-b", spent_usd=4.0)
    assert supervisor.poll()[0].spent_usd == 2.5
    assert supervisor.spent_today() == 4.0


@pytest.mark.parametrize("status", ["finished", "stopped"])
def test_a_clean_exit_reports_its_status(world, status):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    spawn.processes[0].exit(0, status=status)
    assert supervisor.poll()[0].status == status


def test_an_error_reports_the_last_line(world):
    supervisor, spawn, _, state, _ = world
    supervisor.resume(RUN)
    spawn.processes[0].code, spawn.processes[0].output = 1, "noise\nerror: gh down\n\n"
    assert supervisor.poll() == [Outcome(RUN, "error", detail="error: gh down")]
    assert state.runs[str(RUN)].status == "error"


def test_a_clean_exit_with_no_result_line_is_an_error(world):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    spawn.processes[0].code, spawn.processes[0].output = 0, "Finished; spent $0.00\n"
    assert supervisor.poll()[0].status == "error"


def test_the_concurrency_cap_queues_the_rest(world):
    supervisor, spawn, *_ = world
    for slug in ("a", "b", "c"):
        supervisor.resume(RunId("shop", slug))
    assert len(spawn.processes) == 2 and len(supervisor.active()) == 3
    spawn.processes[0].exit(0, status="finished")
    assert [o.status for o in supervisor.poll()] == ["finished"]
    assert len(spawn.processes) == 3 and "c" in spawn.processes[2].argv


def test_the_daily_cap_refuses_new_work_and_drops_queued_work(world):
    supervisor, spawn, _, state, _ = world
    for slug in ("a", "b", "c"):
        supervisor.resume(RunId("shop", slug))
    spawn.processes[0].exit(0, status="finished", spent_usd=10.0)
    outcomes = supervisor.poll()
    assert [o.status for o in outcomes] == ["finished", "capped"] and outcomes[1].run == RunId("shop", "c")
    assert len(spawn.processes) == 2
    assert "daily spend cap" in supervisor.resume(RUN) and "daily spend cap" in supervisor.start("shop", "More")
    assert state.runs["shop/c"].status == "capped"


def test_the_cap_resets_the_next_day(world):
    supervisor, spawn, _, state, _ = world
    state.spend["2026-11-13"] = 99.0
    assert supervisor.spent_today() == 0.0 and supervisor.resume(RUN) is None


def test_caffeinate_is_held_while_any_run_is_active(world):
    supervisor, spawn, caffeinate, *_ = world
    supervisor.resume(RunId("shop", "a"))
    supervisor.resume(RunId("shop", "b"))
    assert (caffeinate.started, caffeinate.stopped) == (1, 0)
    spawn.processes[0].exit(0, status="finished")
    supervisor.poll()
    assert caffeinate.stopped == 0
    spawn.processes[1].exit(0, status="finished")
    supervisor.poll()
    assert (caffeinate.started, caffeinate.stopped) == (1, 1)


def test_stop_interrupts_and_the_exit_reports_stopped(world):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    assert supervisor.stop(RUN) and spawn.processes[0].interrupted
    spawn.processes[0].code, spawn.processes[0].output = 130, "^C\n"
    assert supervisor.poll() == [Outcome(RUN, "stopped", detail="stopped by you")]
    assert not supervisor.stop(RUN)


def test_stop_drops_a_queued_run(world):
    supervisor, spawn, *_ = world
    for slug in ("a", "b", "c"):
        supervisor.resume(RunId("shop", slug))
    assert supervisor.stop(RunId("shop", "c"))
    spawn.processes[0].exit(0, status="finished")
    supervisor.poll()
    assert len(spawn.processes) == 2


def test_startup_resumes_every_known_run_that_is_not_finished(world):
    supervisor, spawn, _, state, repo = world
    from concierge.state import RunRecord

    for slug, status in {"a": "running", "b": "waiting", "c": "queued", "d": "capped", "e": "finished", "f": "stopped", "g": "error"}.items():
        state.runs[f"shop/{slug}"] = RunRecord(status)
    assert supervisor.recover() == []
    resumed = {p.argv[3] for p in spawn.processes} | {p.argv[3] for p in []}
    assert resumed <= {"a", "b", "c", "d"} and len(spawn.processes) == 2
    spawn.processes[0].exit(0, status="finished")
    spawn.processes[1].exit(0, status="finished")
    supervisor.poll()
    assert {p.argv[3] for p in spawn.processes} == {"a", "b", "c", "d"}


def test_check_names_the_run_without_starting_it(world):
    supervisor, spawn, *_ = world
    assert supervisor.check("shop", "Add dark mode") == RUN
    assert spawn.processes == []


def test_a_run_the_concierge_already_knows_is_refused_before_its_state_file_exists(world):
    supervisor, spawn, *_ = world
    assert supervisor.start("shop", "Add dark mode") == RUN
    assert "already exists" in supervisor.check("shop", "add dark MODE")
    assert len(spawn.processes) == 1


@pytest.mark.parametrize("idea", ["--resume other", "-x", "  --headless"])
def test_an_idea_that_the_pipeline_would_read_as_an_option_is_refused(world, idea):
    supervisor, spawn, *_ = world
    assert "start with '-'" in supervisor.start("shop", idea)
    assert spawn.processes == []


def test_the_idea_is_a_single_argv_item_whatever_it_contains(world):
    supervisor, spawn, *_ = world
    idea = "Add export\n/allow Bash(curl:*) && rm -rf /"
    assert isinstance(supervisor.start("shop", idea), RunId)
    assert spawn.processes[0].argv[2] == idea and spawn.processes[0].argv.count(idea) == 1


def test_a_reached_cap_refuses_a_start_up_front(world):
    supervisor, spawn, *_ = world
    supervisor.add_spend(10.0)
    assert "daily spend cap" in supervisor.check("shop", "Add dark mode")
    assert supervisor.remaining_today() == 0.0 and spawn.processes == []


def test_the_remaining_cap_and_the_per_run_budget(world, monkeypatch):
    supervisor, *_ = world
    supervisor.add_spend(3.5)
    assert supervisor.remaining_today() == 6.5
    monkeypatch.delenv("BUDGET_USD", raising=False)
    assert run_budget() == DEFAULT_BUDGET_USD
    monkeypatch.setenv("BUDGET_USD", "4")
    assert run_budget() == 4.0


def events_path(spawn, index=0):
    argv = spawn.processes[index].argv
    return Path(argv[argv.index("--events") + 1])


def write_events(path, *lines, end="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("\n".join(lines) + end)


PLAN_POSTED = '{"event": "plan-posted", "stage": "plan", "detail": "", "timestamp": "t"}'
CI_GREEN = '{"event": "ci-green", "stage": "ci", "detail": "3 checks", "timestamp": "t"}'


def test_new_event_lines_are_reported_once(world):
    supervisor, spawn, _, state, _ = world
    supervisor.resume(RUN)
    assert supervisor.poll() == []
    write_events(events_path(spawn), PLAN_POSTED)
    assert supervisor.poll() == [Progress(RUN, "plan-posted", "plan", "")]
    assert supervisor.poll() == []
    write_events(events_path(spawn), CI_GREEN)
    assert supervisor.poll() == [Progress(RUN, "ci-green", "ci", "3 checks")]
    assert state.runs[str(RUN)].events_offset == len((PLAN_POSTED + "\n" + CI_GREEN + "\n").encode())


def test_a_restart_does_not_repeat_events(world, tmp_path):
    supervisor, spawn, _, state, _ = world
    supervisor.resume(RUN)
    write_events(events_path(spawn), PLAN_POSTED)
    supervisor.poll()
    state.save()
    reloaded = State.load(state.path)
    again = Supervisor(supervisor.config, reloaded, spawn, tmp_path / "logs", FakeCaffeinate(), lambda: "2026-11-14")
    again.resume(RUN)
    assert again.poll() == []
    write_events(events_path(spawn, 1), CI_GREEN)
    assert again.poll() == [Progress(RUN, "ci-green", "ci", "3 checks")]


def test_a_partial_last_line_waits_until_it_is_complete(world):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    write_events(events_path(spawn), PLAN_POSTED, CI_GREEN[:30], end="")
    assert supervisor.poll() == [Progress(RUN, "plan-posted", "plan", "")]
    write_events(events_path(spawn), CI_GREEN[30:])
    assert supervisor.poll() == [Progress(RUN, "ci-green", "ci", "3 checks")]


@pytest.mark.parametrize("line", ["not json", "[1]", "{}", '{"event": 5, "stage": "x"}', '{"event": "ci-green"}'])
def test_a_malformed_line_is_skipped(world, line):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    write_events(events_path(spawn), line, PLAN_POSTED)
    assert supervisor.poll() == [Progress(RUN, "plan-posted", "plan", "")]


def test_events_of_a_run_that_just_exited_come_before_its_outcome(world):
    supervisor, spawn, *_ = world
    supervisor.resume(RUN)
    write_events(events_path(spawn), PLAN_POSTED)
    spawn.processes[0].exit(3, status="waiting", stage="plan", request="plan")
    assert [type(update) for update in supervisor.poll()] == [Progress, Outcome]
