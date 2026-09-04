# Changelog

## 0.3.1 — 2026-09-04

- Non-loopback `--bind` requires TLS (`OKF_MCP_TLS_CERT` + `OKF_MCP_TLS_KEY`) or it is a startup error. Loopback may bind bare.
- Low-latency NFR is scoped to the rsync push path. S3 end-to-end stays bounded by the consumer daemon's pull (`docs/S3.md`).

## 0.3.0 — 2026-09-03

- Replication is **push**, triggered by a directory watcher (`scripts/remote_watch.py`). Debounce default 2s plus batching.
- `remote_rsync.py push` is the documented default. Destination from `$OKF_REPLICA_DEST`. Pull is retained as a backstop. Still no `--delete` by default.
- S3 writer path: local watcher puts objects. Consumer-side daemon pulling to local disk is unchanged (`docs/S3.md`).
- Network MCP: `serve --bind host:port` is an OAuth 2.1 / OIDC resource server. stdio remains the default and unauthenticated. Binding without `OKF_MCP_ISSUER` is a startup error (`docs/AUTH.md`).
- Auth gates access; it does not add verbs. Watcher death is visible on `replica_status`.

## 0.2.0 — 2026-09-03

- `query` verb: cursor-paginated filesystem walk. Not offset.
- `reverse_pointers` reads `pointer.link` files and returns the inverse name on inbound edges.
- `agentic_search` remains a skill, not a verb. Model is configured per deployment (`OKF_AGENTIC_SEARCH_MODEL`).
- Documented S3 path: consumer-side daemon pulling objects to local disk (`docs/S3.md`).

## 0.1.1 — 2026-09-03

- `walk_chronological` walks the replica filesystem and returns metadata only. `get_node` refuses path escape. Artifacts (telemetry/summary/saliency) are omitted from the walk.

## 0.1.0 — 2026-09-03

- Initial scaffold. Spec: okf-plugin#74.
