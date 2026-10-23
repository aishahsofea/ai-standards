# Plan

## Phase 1: Free shipping threshold
- Add `FREE_SHIPPING_FROM = 100.0` and the check in `shipping_cost`, with tests.
- Verify: `pytest tests/test_shipping.py`

## Acceptance criteria
- Orders of $100 or more ship free: Phase 1, `test_large_orders_ship_free`
- Orders under $100 pay the flat rate: Phase 1, `test_small_orders_pay_the_flat_rate`
