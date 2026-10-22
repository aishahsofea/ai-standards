from blog.text import slugify


def post_url(title: str) -> str:
    return f"/posts/{slugify(title)}"
