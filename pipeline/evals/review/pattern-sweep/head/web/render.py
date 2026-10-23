from html import escape


def render_title(title: str) -> str:
    return f"<h1>{escape(title)}</h1>"


def render_comment(author: str, body: str) -> str:
    return f'<div class="comment"><b>{escape(author)}</b><p>{body}</p></div>'


def render_reply(author: str, body: str) -> str:
    return f'<div class="reply"><b>{escape(author)}</b><p>{body}</p></div>'
