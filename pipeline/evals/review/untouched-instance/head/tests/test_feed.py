from web.feed import render_follow


def test_follow_escapes_the_username():
    assert render_follow("<script>") == "<li>&lt;script&gt; followed you</li>"
