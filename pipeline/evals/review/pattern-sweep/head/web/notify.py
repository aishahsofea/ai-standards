def reply_email_html(author: str, body: str) -> str:
    return f"<p>{author} replied:</p><blockquote>{body}</blockquote>"
