# OKF Remote

Replication of an OKF bundle across machines, plus read-only MCP access.

**Spec of record:** [okf-plugin#74](https://github.com/SpillwaveSolutions/okf-plugin/issues/74)

Companion: [okf-time-series](https://github.com/SpillwaveSolutions/okf-time-series) (#72) · [okf-pointers](https://github.com/SpillwaveSolutions/okf-pointers) (#73)

## What this pass ships

- `scripts/remote_rsync.py` — pull-based replica. rsync if present, copytree fallback. No `--delete` by default.
- `scripts/remote_mcp.py` — allow-listed read verbs: `list_nodes`, `get_node`, `walk_chronological`, `reverse_pointers`, `replica_status`.
- Forbidden: any `write_*`, `summarize`, `compact`, `saliency_detect`, `agentic_search` (the last is a skill, not a verb — open question on #74).

stdio only. No bind address. Never hard-code a private remote.

## Multi-host

Same family as second-brain-core. See docs/.

## License

MIT. Copyright 2026 Rick Hightower / contributors.
