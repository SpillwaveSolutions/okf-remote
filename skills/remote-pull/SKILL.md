---
name: remote-pull
description: Backstop pull. Documented default is push via remote-watch. Never invents a remote URL.
---

Pull is a backstop for a watcher that died. The documented default is push:

```bash
OKF_REPLICA_DEST="$OKF_REPLICA_DEST" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/remote_watch.py" --src "$SECOND_BRAIN_ROOT"
```

Backstop:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/remote_rsync.py" pull --src "$SECOND_BRAIN_ROOT" --dest "$OKF_REPLICA_ROOT"
```

Default is no --delete. Destination never hard-coded. Conflict policy is an open question on #74.
