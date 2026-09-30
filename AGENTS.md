# Code Brevity Standard

Prefer the smallest clear, correct change. Clarity and maintainability outrank character count.

## Comments and documentation

- Do not comment code that is already clear from its names and structure.
- Do not add author, date, file-summary, generated, or license boilerplate.
- Add a comment only to preserve a non-obvious **why**: a business constraint, compatibility workaround, security decision, or tricky invariant.
- Keep permitted comments to one concise line. Do not use explanatory comment blocks.
- Public API docstrings are one high-level sentence when they add information not conveyed by the signature and types. Omit parameter tables duplicated by static types.

## Code shape

- Use precise names, types, and small focused functions instead of explanatory prose.
- Prefer modern language features when they improve readability; do not compress logic into clever or dense expressions.
- Do not add dead code, placeholder branches, unused imports, redundant fallbacks, or speculative abstractions.
- Make the narrowest change that fully addresses the request.

## Responses

- Be direct. Report the result and relevant verification without narrating routine steps.
