# Fetching issue data

Detect the host from the URL, then use the matching CLI. Prefer the CLI over
`WebFetch` — auth'd CLIs return full discussion threads and metadata.

## GitLab (`glab`)

Work item / issue URL shape: `https://gitlab.com/<group>/<project>/-/work_items/<n>`
or `.../-/issues/<n>`. GitLab "work items" and "issues" share an IID namespace,
so `glab issue` resolves both.

```sh
# Issue body + metadata (labels, state, assignees, milestone)
glab issue view <n> --repo <group>/<project>

# Include the full discussion thread / comments
glab issue view <n> --repo <group>/<project> --comments

# JSON for precise field extraction
glab issue view <n> --repo <group>/<project> --output json
```

Merge requests:

```sh
glab mr view <n> --repo <group>/<project> --comments
glab mr diff <n> --repo <group>/<project>
```

If `--repo` is omitted inside a cloned repo, `glab` infers it from the remote.
The `<group>/<project>` path is everything between `gitlab.com/` and `/-/` in the URL.

## GitHub (`gh`)

Issue URL shape: `https://github.com/<owner>/<repo>/issues/<n>`.
PR URL shape: `https://github.com/<owner>/<repo>/pull/<n>`.

```sh
# Issue with comments
gh issue view <n> --repo <owner>/<repo> --comments

# JSON fields
gh issue view <n> --repo <owner>/<repo> --json title,body,labels,state,comments

# Pull requests
gh pr view <n> --repo <owner>/<repo> --comments
gh pr diff <n> --repo <owner>/<repo>
```

## Notes

- Follow links found in the issue body/threads (related issues, MRs/PRs, design
  docs) and fetch those too when they affect scope.
- If a CLI isn't installed or auth fails, say so and fall back to `WebFetch` on the
  URL rather than silently guessing the content.
