from concierge.chat import Event, StdinChat
from concierge.notifier import Choice


def chat_with(*lines):
    sent, queue = [], list(lines)
    return StdinChat(lambda timeout: queue.pop(0) if queue else None, sent.append), sent


def test_send_numbers_the_message_and_its_choices():
    chat, sent = chat_with()
    assert chat.send("Plan ready", (Choice("Approve", "approve"), Choice("Reject", "reject"))) == "1"
    assert chat.send("Done") == "2"
    assert sent == ["[1] Plan ready\n  1) Approve\n  2) Reject", "[2] Done"]


def test_a_number_picks_a_choice_on_the_latest_message_with_choices():
    chat, _ = chat_with("2")
    chat.send("Plan", (Choice("Approve", "approve"), Choice("Reject", "reject")))
    chat.send("Note")
    assert chat.poll(0) == [Event("button", data="reject", message_id="1")]


def test_at_id_targets_a_message():
    chat, _ = chat_with("@1 1", "@1 make it a modal", "@9 1")
    chat.send("A", (Choice("Approve", "approve"),))
    chat.send("B", (Choice("Reject", "reject"),))
    assert chat.poll(0) == [Event("button", data="approve", message_id="1")]
    assert chat.poll(0) == [Event("text", text="make it a modal", message_id="1")]
    assert chat.poll(0) == [Event("text", text="@9 1")]


def test_plain_words_are_text_and_a_number_with_no_choices_is_text():
    chat, _ = chat_with("ship it", "3", "", None)
    assert chat.poll(0) == [Event("text", text="ship it")]
    assert chat.poll(0) == [Event("text", text="3")]
    assert chat.poll(0) == [] and chat.poll(0) == []
