from concierge.notifier import Choice, build_prompt
from concierge.requests import find_request
from fakes import FakeIssue

LONG = "Needs a captured fixture. " * 120
PLAN = f"# Plan\n\n## Prerequisites\n{LONG}\n\n## Commands\n- Run the tests: `pytest -q tests/`\n- Build: `make build`\n\n## Phase 1: Add the toggle\n- Verify: pytest\n\n## Phase 2: Persist it\n\n## Assumptions\nNone.\n\n## Out of scope\nThemes.\n"
DECISIONS = "## Decided from evidence\nNone.\n\n## Escalated\n1. Which database?\n  Answer: sqlite\n2. Which cache?\n  Recommendation: redis\n3. Which queue?\n  Recommendation: none\n"


def prompt_for(issue, key):
    return build_prompt(find_request(issue.comments(), key), issue.comments())


def labels(prompt):
    return [(choice.label, choice.data) for choice in prompt.choices]


def test_baseline_shows_the_failing_checks_with_approve_and_reject():
    issue = FakeIssue()
    issue.request("baseline", "The checks fail before any change:\n- pytest: 9 failed\n\nReply `/approve` or `/reject`.")
    prompt = prompt_for(issue, "baseline")
    assert "pytest: 9 failed" in prompt.text and prompt.text.endswith(issue.items[-1].url)
    assert labels(prompt) == [("Approve", "approve"), ("Reject", "reject")]


def test_gate_a_lists_only_the_open_questions_by_number():
    issue = FakeIssue()
    issue.artifact("decisions", DECISIONS)
    issue.request("gate-a", "asked")
    prompt = prompt_for(issue, "gate-a")
    assert "Q2: Which cache?" in prompt.text and "Recommendation: redis" in prompt.text and "Q3: Which queue?" in prompt.text
    assert "Which database" not in prompt.text
    assert labels(prompt) == [("Accept every recommendation", "approve")]


def test_the_plan_shows_its_commands_verbatim_even_when_the_rest_is_cut():
    issue = FakeIssue()
    issue.artifact("plan", PLAN)
    issue.request("plan", "asked")
    prompt = prompt_for(issue, "plan")
    assert "- `pytest -q tests/`" in prompt.text and "- `make build`" in prompt.text
    assert "1. Add the toggle" in prompt.text and len(prompt.text) < 3600
    assert labels(prompt) == [("Approve plan", "approve"), ("Reject", "reject")]


def test_gate_b_shows_the_pr_and_the_head_commit():
    issue = FakeIssue()
    issue.artifact("pr", "Adds a dark mode toggle.\n\n- tests added")
    issue.request("gate-b", "Reviewed?\n\nHead commit: `abc123`\n\nReply.")
    prompt = prompt_for(issue, "gate-b")
    assert "Adds a dark mode toggle." in prompt.text and "Head commit: `abc123`" in prompt.text
    assert labels(prompt) == [("Approve", "approve"), ("Revise", "revise"), ("Reject", "reject")]


def test_allow_offers_one_button_per_rule_the_request_lists():
    issue = FakeIssue()
    issue.request("allow", "Denied.\n\n- `/allow Bash(docker ps:*)`\n- `/allow Bash(make:*)`")
    prompt = prompt_for(issue, "allow")
    assert "- `/allow Bash(docker ps:*)`" in prompt.text
    assert labels(prompt) == [("Allow Bash(docker ps:*)", "allow:0"), ("Allow Bash(make:*)", "allow:1")]
    assert prompt.rules == ["Bash(docker ps:*)", "Bash(make:*)"]


def test_a_long_request_is_cut_to_a_phone_sized_message_that_keeps_the_link():
    issue = FakeIssue()
    issue.request("baseline", "x" * 20_000)
    prompt = prompt_for(issue, "baseline")
    assert len(prompt.text) < 3600 and prompt.text.endswith(issue.items[-1].url)


def test_choice_is_a_label_and_data():
    assert Choice("Approve", "approve").data == "approve"
