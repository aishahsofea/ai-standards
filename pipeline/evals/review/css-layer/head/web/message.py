from html import escape


def render_user_message(text: str) -> str:
    return f'<div class="bubble-user bubble-select">{escape(text)}</div>'
