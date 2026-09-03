# OKF Remote

Replication of an OKF bundle across machines, plus read-only MCP access.

**Spec of record:** [okf-plugin#74](https://github.com/SpillwaveSolutions/okf-plugin/issues/74)

Companion: [okf-time-series](https://github.com/SpillwaveSolutions/okf-time-series) (#72) · [okf-pointers](https://github.com/SpillwaveSolutions/okf-pointers) (#73)

## What this pass ships

- `scripts/remote_rsync.py` — pull-based replica. rsync if present, copytree fallback. No `--delete` by default.
- `scripts/remote_mcp.py` — allow-listed read verbs: `list_nodes`, `get_node`, `walk_chronological`, `query`, `reverse_pointers`, `replica_status`.
- `query` is **cursor-paginated**. Not offset — the bundle is a live filesystem and offsets drift under concurrent writes.
- `reverse_pointers` reads `pointer.link` files and returns the inverse name on inbound edges.
- Forbidden: any `write_*`, `summarize`, `compact`, `saliency_detect`, `agentic_search` (the last is a skill, not a verb).
- `agentic_search` model is configured per deployment (`OKF_AGENTIC_SEARCH_MODEL`), never pinned.
- S3 default is a consumer-side daemon pulling objects to local disk. See [docs/S3.md](docs/S3.md).

stdio only. No bind address. Never hard-code a private remote.

## Multi-host

Same family as second-brain-core. See docs/.

## License

MIT. Copyright 2026 Rick Hightower / contributors.
