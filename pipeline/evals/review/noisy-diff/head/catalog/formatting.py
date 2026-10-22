def format_price(cents: int) -> str:
    if cents < 0:
        raise ValueError("price cannot be negative")
    return f"${cents // 100}.{cents % 100:02d}"
