# Retry failed fetches in the sync job

## Problem
A single network blip fails the nightly sync.

## Proposed design
Retry `fetch_page` a few times before giving up.

## Acceptance criteria
- A transient failure is retried.
- After the last retry the error is raised.
