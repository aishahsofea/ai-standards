# AI coding standards

Reusable, agent-facing standards for repositories that use coding assistants. The initial standard targets a common failure mode: comments that merely paraphrase the code.

## Recommended installation

Publish this repository, then add it to each consuming project at a stable path:

```sh
git submodule add <standards-repository-url> .agent/standards
```

Create or update the consuming repository's root `AGENTS.md` with this bootstrap instruction, followed by that repository's own rules:

```md
# Shared agent standards

Read and follow `.agent/standards/AGENTS.md` before editing code. Rules in this repository's `AGENTS.md` take precedence when they conflict.
```

Codex automatically loads a root `AGENTS.md`; the short bootstrap makes it load the shared standard explicitly. This is more portable than a symlink and leaves room for project-specific rules.

For a project with no local agent rules, macOS/Linux users may instead track a symlink so the shared rules are loaded automatically:

```sh
ln -s .agent/standards/AGENTS.md AGENTS.md
git add AGENTS.md
```

Do not combine that symlink with a local root `AGENTS.md`.

## Updating consuming projects

```sh
git submodule update --remote .agent/standards
git add .agent/standards
git commit -m "Update AI standards"
```

Pinning the submodule commit makes standards changes reviewable and prevents an unexpected policy change from altering agent behavior mid-project.

## Principles

- Put short, universal behavior in `AGENTS.md`.
- Keep detailed, task-specific workflows in separate documents and reference them only when relevant.
- Prefer reviewable policy updates over broad, absolute wording such as "always use one-liners." Brevity should remove noise, not reduce readability or correctness.
