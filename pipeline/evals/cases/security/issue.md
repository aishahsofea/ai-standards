# Authenticate incoming webhooks with API tokens

## Problem
Anyone can post to `/hooks/orders`.

## Proposed design
Require a bearer token on webhook requests.

## Acceptance criteria
- Requests without a valid token get 401.
- Valid tokens are accepted.
