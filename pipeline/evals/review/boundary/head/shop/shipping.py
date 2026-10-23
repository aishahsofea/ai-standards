FLAT_RATE = 4.99
FREE_SHIPPING_FROM = 100.0


def shipping_cost(subtotal: float) -> float:
    if subtotal > FREE_SHIPPING_FROM:
        return 0.0
    return FLAT_RATE
