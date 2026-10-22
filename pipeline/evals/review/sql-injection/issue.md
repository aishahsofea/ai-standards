# Look up a user by email

## Problem
The sign-in form takes an email address, but there is no way to find the matching user.

## Proposed design
Add `find_by_email` to `app/users.py`. The email comes straight from the sign-in form.

## Acceptance criteria
- A known email returns that user's id, name and email.
- An unknown email returns `None`.
