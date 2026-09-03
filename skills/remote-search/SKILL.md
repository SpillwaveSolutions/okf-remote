---
name: remote-search
description: AGER skill that uses MCP read verbs. Model is configured per deployment. Not a write. Not a processing verb.
---

`agentic_search` is a skill, not an MCP verb. Compile an AGER graph from okf-agent-graph; do not build a new agent loop.

The model is **configured per deployment**, never pinned in this plugin:

```bash
# operator sets this; the skill reads it. Do not hard-code a model id.
echo "$OKF_AGENTIC_SEARCH_MODEL"
```

Do not call summarize/compact/saliency_detect. Walk with `query` (cursor-paginated) or `walk_chronological` + `get_node`. Reverse-lookup tickets with `reverse_pointers` — inbound hits return the inverse `link_type`.
