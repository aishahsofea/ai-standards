# Definition of done

Built-in default, used when the target repo has no `DEFINITION_OF_DONE.md`.

- Every new behavior has a test that fails without the change.
- Existing tests, lint, and build still pass.
- No dead code, commented-out code, or leftover debug output.
- The diff touches only what the issue and plan call for.
- Names and structure match the surrounding code.
- Errors and edge cases the issue implies are handled.
- Docs that the change makes wrong or incomplete are updated.
- No secrets, credentials, or unrelated files are committed.
