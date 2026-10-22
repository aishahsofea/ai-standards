from shop.shipping import FLAT_RATE, shipping_cost


def test_large_orders_ship_free():
    assert shipping_cost(150.0) == 0.0


def test_small_orders_pay_the_flat_rate():
    assert shipping_cost(40.0) == FLAT_RATE
