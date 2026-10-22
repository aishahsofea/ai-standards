from html import escape


def render_title(title: str) -> str:
    return f"<h1>{escape(title)}</h1>"
