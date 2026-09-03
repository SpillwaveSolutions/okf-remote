---
name: grok-bot-okf-remote
description: Bind a Grok Bot agent to okf-remote. Isolation, identity, deterministic writes.
---

# Grok Bot / okf-remote

Read docs/ONBOARDING.md first, then follow docs/GROK_BOT.md.

1. Identity: `grok-bot/okf-remote`
2. Open an isolation session before writes (second-brain-core `scripts/brain_session.py open`) unless the human already pointed `SECOND_BRAIN_ROOT` at a session worktree.
3. Write owned types only (none — this plugin does not write knowledge nouns) via this pack's scripts + `--author`.
4. Close the session to PR. Report path + SHA.
5. Never document a private remote. Never write raw Markdown into the tree.
