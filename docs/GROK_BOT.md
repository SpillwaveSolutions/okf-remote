# Grok Bot binding — okf-remote

Identity: `grok-bot/okf-remote`

Owned types: none (read-only) — replica.manifest is local

Write path: pack scripts + `--author`. The model proposes prose; scripts commit frontmatter.

Isolation: second-brain-core worktree + PR. Point `SECOND_BRAIN_ROOT` at the session bundle.

Never hard-code a private remote. Never invent `rel` values. Never write types owned by another plugin.
