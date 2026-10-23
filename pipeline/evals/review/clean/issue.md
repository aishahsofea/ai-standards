# Item count for the cart

## Problem
The cart badge needs the number of items, and nothing computes it.

## Proposed design
Add `item_count(prices)` next to `cart_total` in `shop/cart.py`.

## Acceptance criteria
- A cart with three items has a count of 3.
- An empty cart has a count of 0.
