from web.forms import render_submit


def test_submit_shows_loading_state():
    assert "is-loading" in render_submit("Pay", loading=True)


def test_submit_is_normal_when_idle():
    assert "is-loading" not in render_submit("Pay")
