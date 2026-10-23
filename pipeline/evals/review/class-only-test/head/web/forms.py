def render_submit(label: str, loading: bool = False) -> str:
    classes = "submit is-loading" if loading else "submit"
    return f'<button type="submit" class="{classes}">{label}</button>'
