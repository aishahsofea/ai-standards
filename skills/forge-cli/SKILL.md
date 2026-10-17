---
name: forge-cli
description: Use the glab or gh CLI to fetch issues, merge requests, pull requests, comments, discussions, and related data instead of guessing or using WebFetch. Use when the user pastes a gitlab.com or github.com link, or asks about an issue, MR, PR, comment, thread, review, or CI pipeline on either platform.
---

# forge-cli

When the user references something on GitLab or GitHub — especially by pasting a link — fetch it with the right CLI rather than `WebFetch` or guessing. Both `glab` and `gh` are installed and authenticated.

## Pick the tool from the host

- `gitlab.com` / self-managed GitLab → **`glab`**
- `github.com` → **`gh`**

## Get the content, don't just open it

Always pull the actual data into context (use `--repo`/`-R` so you don't depend on the current directory):

| What | GitLab (`glab`) | GitHub (`gh`) |
|---|---|---|
| Issue + comments | `glab issue view <id> --comments -R group/proj` | `gh issue view <id> --comments -R owner/repo` |
| MR / PR + comments | `glab mr view <id> --comments -R group/proj` | `gh pr view <id> --comments -R owner/repo` |
| Diff | `glab mr diff <id> -R group/proj` | `gh pr diff <id> -R owner/repo` |
| CI / checks | `glab ci status -R group/proj` | `gh pr checks <id> -R owner/repo` |
| Anything else | `glab api <path>` | `gh api <path>` |

For data the subcommands don't expose (inline review threads, reactions, specific note IDs, label history), drop to `glab api` / `gh api` with the REST or GraphQL endpoint.

## Parsing a pasted link

From `https://gitlab.com/gitlab-org/gitlab/-/issues/123`:
- host → `glab`, repo → `gitlab-org/gitlab`, id → `123`, type → issue (`-/merge_requests/` → MR).

From `https://github.com/cli/cli/pull/456`:
- host → `gh`, repo → `cli/cli`, id → `456`, type → PR (`/issues/` → issue).

A `#note_<id>` or `#note-<id>` fragment points at a specific comment — fetch all comments, then find that one.

## Notes

- Add `-F json` (glab) or `--json <fields>` (gh) when you need structured output to filter or extract fields.
- Headless: never ask questions; if a command fails, say so in the output and stop that step.
- If a command fails with auth/not-found, report the failure and the exact command — don't silently fall back to scraping the web page.
