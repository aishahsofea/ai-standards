from web.notify import reply_email_html
from web.render import render_comment, render_reply


def test_render_comment_shows_author_and_body():
    assert render_comment("Ana", "Nice post") == '<div class="comment"><b>Ana</b><p>Nice post</p></div>'


def test_render_reply_shows_author_and_body():
    assert render_reply("Bo", "Thanks") == '<div class="reply"><b>Bo</b><p>Thanks</p></div>'


def test_reply_email_quotes_the_reply():
    assert reply_email_html("Bo", "Thanks") == "<p>Bo replied:</p><blockquote>Thanks</blockquote>"
