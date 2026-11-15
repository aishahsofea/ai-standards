import pytest

from concierge.actions import Action, Answer
from concierge.poster import Posted, Poster, Refused
from concierge.requests import find_request
from concierge.state import Bound, RunId, State
from fakes import FakeIssue
from pipeline.forge import Decision, first_command

RUN = RunId("shop", "dark-mode")
GATE_B = "Ready.\n\nHead commit: `abc123`\n\nReply."
ALLOW = "Denied.\n\n- `/allow Bash(docker ps:*)`\n- `/allow Bash(make:*)`"
DECISIONS = "## Escalated\n1. Which database?\n2. Which cache?\n"


def bound(issue, key):
    request = find_request(issue.comments(), key)
    return Bound(key, request.comment_id, request.digest, request.head)


@pytest.fixture
def issue():
    fake = FakeIssue()
    fake.head_commit = "abc123"
    return fake


@pytest.fixture
def poster(tmp_path, issue):
    state = State(tmp_path / "state.json")
    return Poster(state, lambda run: issue), state


def test_posts_the_comment_the_pipeline_reads_as_that_decision(poster, issue):
    poster, state = poster
    issue.request("gate-b", GATE_B)
    result = poster.post(RUN, bound(issue, "gate-b"), Action("approve"))
    assert isinstance(result, Posted) and issue.posted == [result.comment_id]
    assert first_command([issue.items[-1].body]) == Decision("approve")
    assert state.posted == [(str(RUN), result.comment_id)]


def test_a_revise_carries_the_feedback(poster, issue):
    poster, _ = poster
    issue.request("gate-b", GATE_B)
    poster.post(RUN, bound(issue, "gate-b"), Action("revise", feedback="use a modal"), "looks good but use a modal")
    assert first_command([issue.items[-1].body]) == Decision("revise", "use a modal")


def refused(poster, issue, key, action, reason, seen=None):
    poster, _ = poster
    result = poster.post(RUN, seen or bound(issue, key), action)
    assert isinstance(result, Refused) and reason in result.reason
    assert issue.posted == []


def test_refuses_when_the_request_was_withdrawn(poster, issue):
    comment_id = issue.request("plan", "p")
    seen = bound(issue, "plan")
    issue.delete(comment_id)
    refused(poster, issue, "plan", Action("approve"), "withdrawn", seen)


def test_refuses_when_the_request_was_replaced_by_a_new_one(poster, issue):
    comment_id = issue.request("gate-b", GATE_B)
    seen = bound(issue, "gate-b")
    issue.delete(comment_id)
    issue.request("gate-b", GATE_B.replace("abc123", "def456"))
    refused(poster, issue, "gate-b", Action("approve"), "changed", seen)


def test_refuses_when_the_request_text_was_edited_in_place(poster, issue):
    comment_id = issue.request("allow", ALLOW)
    seen = bound(issue, "allow")
    issue.replace_text(comment_id, "allow", ALLOW + "\n- `/allow Bash(rm:*)`")
    refused(poster, issue, "allow", Action("allow", rule="Bash(make:*)"), "changed", seen)


@pytest.mark.parametrize("earlier", ["/approve", "/reject", "/revise change it"])
def test_refuses_when_the_request_already_has_a_decision(poster, issue, earlier):
    issue.request("plan", "p")
    seen = bound(issue, "plan")
    issue.reply(earlier)
    refused(poster, issue, "plan", Action("approve"), "already decided", seen)


def test_a_decision_from_a_stranger_does_not_count(poster, issue):
    issue.request("plan", "p")
    issue.reply("/reject", "NONE")
    poster, _ = poster
    assert isinstance(poster.post(RUN, bound(issue, "plan"), Action("approve")), Posted)


def test_refuses_when_the_branch_moved_since_the_user_saw_it(poster, issue):
    issue.request("gate-b", GATE_B)
    issue.head_commit = "def456"
    refused(poster, issue, "gate-b", Action("approve"), "branch moved")


@pytest.mark.parametrize(
    ("key", "action", "reason"),
    [
        ("plan", Action("revise", feedback="x"), "the plan step only takes approve or reject"),
        ("gate-b", Action("revise"), "no feedback"),
        ("allow", Action("allow", rule="Bash(rm:*)"), "not one the request lists"),
        ("allow", Action("approve"), "only takes allow"),
    ],
)
def test_refuses_an_action_the_request_does_not_take(poster, issue, key, action, reason):
    issue.request(key, ALLOW if key == "allow" else GATE_B)
    refused(poster, issue, key, action, reason)


def test_an_allowed_rule_is_posted_once(poster, issue):
    issue.request("allow", ALLOW)
    seen = bound(issue, "allow")
    poster, _ = poster
    assert isinstance(poster.post(RUN, seen, Action("allow", rule="Bash(make:*)")), Posted)
    assert isinstance(poster.post(RUN, seen, Action("allow", rule="Bash(docker ps:*)")), Posted)
    result = poster.post(RUN, seen, Action("allow", rule="Bash(make:*)"))
    assert isinstance(result, Refused) and "already allowed" in result.reason and len(issue.posted) == 2


def test_answers_must_name_an_open_question(poster, issue):
    issue.artifact("decisions", DECISIONS)
    issue.request("gate-a", "asked")
    refused(poster, issue, "gate-a", Action("answer", answers=(Answer(7, "x"),)), "no open question Q7")
    poster, _ = poster
    assert isinstance(poster.post(RUN, bound(issue, "gate-a"), Action("answer", answers=(Answer(2, "redis"),))), Posted)


def test_answers_may_follow_earlier_answers(poster, issue):
    issue.artifact("decisions", DECISIONS)
    issue.request("gate-a", "asked")
    issue.reply("Q1: sqlite")
    poster, _ = poster
    assert isinstance(poster.post(RUN, bound(issue, "gate-a"), Action("answer", answers=(Answer(2, "redis"),))), Posted)


def test_undo_deletes_the_last_comment_it_posted(poster, issue):
    poster, state = poster
    issue.request("plan", "p")
    first = poster.post(RUN, bound(issue, "plan"), Action("approve"))
    assert poster.undo(RUN) == first.comment_id
    assert issue.deleted == [first.comment_id] and state.posted == []
    assert poster.undo(RUN) is None
