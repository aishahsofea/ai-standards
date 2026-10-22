from shop.cart import cart_total, item_count


def test_cart_total_sums_prices():
    assert cart_total([1.5, 2.5]) == 4.0


def test_item_count_counts_items():
    assert item_count([1.5, 2.5, 3.0]) == 3


def test_item_count_of_empty_cart_is_zero():
    assert item_count([]) == 0
