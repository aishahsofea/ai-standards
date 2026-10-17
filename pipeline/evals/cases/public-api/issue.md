# Add CSV export endpoint

## Problem
Users cannot download their orders.

## Proposed design
Add `GET /api/v1/orders.csv` returning the signed-in user's orders.

## Acceptance criteria
- The endpoint returns a CSV file.
- Only the caller's orders are included.
