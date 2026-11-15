from concierge.requests import allow_rules, decision_on, find_request, open_questions
from fakes import FakeIssue
from pipeline.forge import Decision

GATE_B = "Ready.\n\nHead commit: `abc123`\n\nReply `/approve`."
ALLOW = "Denied.\n\n- `/allow Bash(docker ps:*)`\n- `/allow Bash(make:*)`"


def test_finds_the_request_with_its_comment_id_and_head():
    issue = FakeIssue()
    issue.reply("hello")
    comment_id = issue.request("gate-b", GATE_B)
    request = find_request(issue.comments(), "gate-b")
    assert (request.key, request.comment_id, request.head) == ("gate-b", comment_id, "abc123")
    assert "Reply `/approve`." in request.text and request.url.endswith(f"issuecomment-{comment_id}")


def test_no_request_is_none():
    assert find_request(FakeIssue().comments(), "plan") is None


def test_the_digest_changes_when_the_text_does():
    issue = FakeIssue()
    comment_id = issue.request("allow", ALLOW)
    before = find_request(issue.comments(), "allow")
    issue.replace_text(comment_id, "allow", ALLOW + "\n- `/allow Bash(rm:*)`")
    assert find_request(issue.comments(), "allow").digest != before.digest


def test_the_decision_is_the_first_trusted_command_after_the_request():
    issue = FakeIssue()
    issue.reply("/reject")
    issue.request("plan", "p")
    request = find_request(issue.comments(), "plan")
    assert decision_on(issue.comments(), request) is None
    issue.reply("/approve", "NONE")
    issue.reply("> /reject\nmaybe")
    assert decision_on(issue.comments(), request) is None
    issue.reply("/approve")
    issue.reply("/reject")
    assert decision_on(issue.comments(), request) == Decision("approve")


def test_allow_rules_are_read_verbatim_from_the_request():
    issue = FakeIssue()
    issue.request("allow", ALLOW)
    assert allow_rules(find_request(issue.comments(), "allow")) == ["Bash(docker ps:*)", "Bash(make:*)"]


def test_open_questions_are_numbered_from_the_decisions_comment():
    issue = FakeIssue()
    issue.artifact(
        "decisions",
        "## Decided from evidence\nNone.\n\n## Escalated\n1. Which database?\n  Answer: sqlite\n2. Which cache?\n  Recommendation: redis\n3. Which queue?\n",
    )
    assert open_questions(issue.comments()) == {2: "Which cache?\n  Recommendation: redis", 3: "Which queue?"}


def test_no_decisions_comment_means_no_open_questions():
    assert open_questions(FakeIssue().comments()) == {}
