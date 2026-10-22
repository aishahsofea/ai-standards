from web.message import render_user_message


def test_user_message_uses_the_bubble_selection_highlight():
    assert "bubble-select" in render_user_message("hi")


def test_user_message_escapes_text():
    assert "&lt;b&gt;" in render_user_message("<b>")
