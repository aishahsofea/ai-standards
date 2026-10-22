# Tag pages

## Problem
Tags have no URL, so they cannot link to a page.

## Proposed design
Add `tag_url(name)` that returns `/tags/<slug>`, slugged the same way as post URLs.

## Acceptance criteria
- `tag_url("Machine Learning")` returns `/tags/machine-learning`.
