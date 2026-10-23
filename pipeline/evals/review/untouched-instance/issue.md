# Usernames run as HTML in the activity feed

## Problem
The activity feed puts usernames into HTML as they are. A user named `<script>...</script>` runs code for everyone whose feed shows them.

## Proposed design
Escape usernames everywhere in the activity feed.

## Acceptance criteria
- No username in the feed is rendered as HTML.
