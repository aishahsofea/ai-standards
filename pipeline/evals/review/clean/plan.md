# Plan

## Phase 1: item_count
- Add `item_count` to `shop/cart.py`, with tests.
- Verify: `pytest tests/test_cart.py`

## Acceptance criteria
- Three items count as 3: Phase 1, `test_item_count_counts_items`
- Empty cart counts as 0: Phase 1, `test_item_count_of_empty_cart_is_zero`
