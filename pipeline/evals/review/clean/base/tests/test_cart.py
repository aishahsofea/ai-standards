from shop.cart import cart_total


def test_cart_total_sums_prices():
    assert cart_total([1.5, 2.5]) == 4.0
