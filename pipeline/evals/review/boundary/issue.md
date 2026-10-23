# Free shipping on orders of $100 or more

## Problem
Every order pays the flat shipping rate.

## Proposed design
In `shop/shipping.py`, return 0 shipping when the subtotal is $100 or more.

## Acceptance criteria
- Orders of $100 or more ship free.
- Orders under $100 pay the flat rate.
