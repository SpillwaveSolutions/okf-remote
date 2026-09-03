# Changelog

## 0.2.0 — 2026-09-03

- `query` verb: cursor-paginated filesystem walk. Not offset.
- `reverse_pointers` reads `pointer.link` files and returns the inverse name on inbound edges.
- `agentic_search` remains a skill, not a verb. Model is configured per deployment (`OKF_AGENTIC_SEARCH_MODEL`).
- Documented S3 path: consumer-side daemon pulling objects to local disk (`docs/S3.md`).

## 0.1.1 — 2026-09-03

- `walk_chronological` walks the replica filesystem and returns metadata only. `get_node` refuses path escape. Artifacts (telemetry/summary/saliency) are omitted from the walk.

## 0.1.0 — 2026-09-03

- Initial scaffold. Spec: okf-plugin#74.
