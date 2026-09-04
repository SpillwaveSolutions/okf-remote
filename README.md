# OKF Remote

Replication of an OKF bundle across machines, plus read-only MCP access.

**Spec of record:** [okf-plugin#74](https://github.com/SpillwaveSolutions/okf-plugin/issues/74)

Companion: [okf-time-series](https://github.com/SpillwaveSolutions/okf-time-series) (#72) · [okf-pointers](https://github.com/SpillwaveSolutions/okf-pointers) (#73)

## What this pass ships

- **Push replication.** A directory watcher observes `$SECOND_BRAIN_ROOT` and hands changed files to a transport. Destination from `$OKF_REPLICA_DEST` — never a hard-coded host.
- Watcher coalesces: debounce (~2s) plus batching. Finalizing a node does not fire one rsync per file write.
- `scripts/remote_rsync.py push` — rsync push, or S3 put when `$OKF_REPLICA_DEST` is `s3://…`. Pull remains a backstop (`pull` / legacy flags). No `--delete` by default.
- `scripts/remote_mcp.py` — allow-listed read verbs: `list_nodes`, `get_node`, `walk_chronological`, `query`, `reverse_pointers`, `replica_status`.
- stdio is the default transport (unauthenticated). `--bind host:port` runs an OAuth 2.1 / OIDC resource server. Binding without `OKF_MCP_ISSUER` is a startup error. See [docs/AUTH.md](docs/AUTH.md).
- `query` is **cursor-paginated**. Not offset.
- `reverse_pointers` reads `pointer.link` files and returns the inverse name on inbound edges.
- Forbidden: any `write_*`, `summarize`, `compact`, `saliency_detect`, `agentic_search` (the last is a skill, not a verb). Auth does not add verbs.
- S3 writer path is watcher put; consumer path is a daemon pulling to local disk. See [docs/S3.md](docs/S3.md).

Never hard-code a private remote. Northstar / Lumenfield fiction only.

## Multi-host

Same family as second-brain-core. See docs/.

## License

MIT. Copyright 2026 Rick Hightower / contributors.
