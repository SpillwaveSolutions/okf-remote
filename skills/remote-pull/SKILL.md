---
name: remote-pull
description: rsync (or copytree fallback) from SECOND_BRAIN_ROOT to OKF_REPLICA_ROOT. Never invents a remote URL.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/remote_rsync.py" --src "$SECOND_BRAIN_ROOT" --dest "$OKF_REPLICA_ROOT"
```

Default is no --delete. Conflict policy is an open question on #74.
