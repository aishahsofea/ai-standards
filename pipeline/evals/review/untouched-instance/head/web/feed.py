from html import escape


def render_follow(username: str) -> str:
    return f"<li>{escape(username)} followed you</li>"


def render_like(username: str, post_title: str) -> str:
    return f"<li>{username} liked {escape(post_title)}</li>"


def render_feed(items: list[str]) -> str:
    return f'<ul class="feed">{"".join(items)}</ul>'
