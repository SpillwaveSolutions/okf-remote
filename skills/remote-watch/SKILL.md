---
name: remote-watch
description: Watch SECOND_BRAIN_ROOT and push coalesced batches to OKF_REPLICA_DEST.
---

```bash
OKF_REPLICA_DEST="$OKF_REPLICA_DEST" python3 "${CLAUDE_PLUGIN_ROOT}/scripts/remote_watch.py" \
  --src "$SECOND_BRAIN_ROOT" --debounce 2
```

- Destination strictly from `$OKF_REPLICA_DEST`. Missing dest is a clean error. Never a hard-coded host.
- Debounce default 2s plus batching. Ten files written in one burst produce one transfer.
- `s3://bucket/prefix` selects the S3 put transport. Consumer-side pull daemon is unchanged.
- `--exclude-telemetry` drops raw telemetry.
- Watcher death is visible in `replica_status`.
