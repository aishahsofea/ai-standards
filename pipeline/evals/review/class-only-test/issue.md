# Double submits create duplicate orders

## Problem
Customers who click Pay twice, or press Enter twice, get charged for two orders.

## Proposed design
While the order is submitting, render the Pay button in a loading state.

## Acceptance criteria
- While loading, the Pay button cannot be clicked or submitted with Enter.
- While loading, the button looks busy.
