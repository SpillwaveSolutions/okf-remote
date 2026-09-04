#!/usr/bin/env python3
"""Directory watcher. Push on write, coalesced.

A watcher observes $SECOND_BRAIN_ROOT and hands changed files to a transport
(rsync push or S3 put). Debounce (default 2s) plus batching so finalizing a
node does not fire one rsync per file write.

Destination strictly from $OKF_REPLICA_DEST. Missing dest is a clean error.
Watcher death is visible in replica_status via a heartbeat file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remote_rsync import cmd_push  # noqa: E402

HEARTBEAT = ".okf-watcher-heartbeat.json"
DEFAULT_DEBOUNCE = 2.0
STALE_AFTER = 10.0


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dest_from_env() -> str:
    return (os.environ.get("OKF_REPLICA_DEST") or "").strip()


@dataclass
class Coalescer:
    debounce_s: float = DEFAULT_DEBOUNCE
    pending: set[str] = field(default_factory=set)
    last_event: float | None = None

    def note(self, path: str, now_ts: float | None = None) -> None:
        self.pending.add(path)
        self.last_event = now_ts if now_ts is not None else time.time()

    def due(self, now_ts: float | None = None) -> bool:
        if not self.pending or self.last_event is None:
            return False
        return (now_ts if now_ts is not None else time.time()) - self.last_event >= self.debounce_s

    def take(self) -> list[str]:
        batch = sorted(self.pending)
        self.pending.clear()
        self.last_event = None
        return batch


def scan_mtimes(root: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name in {HEARTBEAT, "replica.manifest.json"}:
            continue
        try:
            out[str(p.relative_to(root))] = p.stat().st_mtime
        except OSError:
            continue
    return out


def write_heartbeat(root: Path, extra: dict | None = None) -> Path:
    payload = {
        "alive": True,
        "heartbeat_at": now(),
        "pid": os.getpid(),
        "dest": dest_from_env(),
    }
    if extra:
        payload.update(extra)
    path = root / HEARTBEAT
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_heartbeat(root: Path, stale_after: float = STALE_AFTER) -> dict:
    path = root / HEARTBEAT
    if not path.exists():
        return {"alive": False, "error": "watcher not running", "heartbeat_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"alive": False, "error": f"heartbeat unreadable: {exc}", "heartbeat_at": None}
    age = time.time() - path.stat().st_mtime
    if age > stale_after:
        data["alive"] = False
        data["error"] = "watcher heartbeat stale"
        data["age_s"] = age
        return data
    data["alive"] = True
    return data


class Namespace:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def dispatch_push(src: Path, paths: list[str], *, exclude_telemetry: bool, replica_id: str = "") -> dict:
    dest = dest_from_env()
    if not dest:
        return {"ok": False, "error": "destination required", "hint": "OKF_REPLICA_DEST — never a hard-coded remote"}
    filtered = paths
    if exclude_telemetry:
        filtered = [p for p in paths if not (p.endswith(".telemetry.md") or ".telemetry_" in p)]
    args = Namespace(
        src=str(src),
        dest=dest,
        replica_id=replica_id,
        dry_run=False,
        delete=False,
        exclude_telemetry=exclude_telemetry,
        paths=filtered,
    )
    rc = cmd_push(args)
    result = {"ok": rc == 0, "rc": rc, "count": len(filtered), "dest": dest}
    if rc == 0 and dest and not dest.startswith("s3://"):
        write_heartbeat(Path(dest).expanduser(), extra={"last_batch": len(filtered), "last_ok": True, "transport": "s3-push" if dest.startswith("s3://") else "rsync-push"})
    return result


def watch_once(src: Path, coalescer: Coalescer, previous: dict[str, float], *, exclude_telemetry: bool, replica_id: str, now_ts: float | None = None) -> tuple[dict[str, float], dict | None]:
    current = scan_mtimes(src)
    for rel, mtime in current.items():
        if previous.get(rel) != mtime:
            coalescer.note(rel, now_ts)
    flushed = None
    if coalescer.due(now_ts):
        batch = coalescer.take()
        result = dispatch_push(src, batch, exclude_telemetry=exclude_telemetry, replica_id=replica_id)
        write_heartbeat(src, extra={"last_batch": len(batch), "last_ok": result.get("ok"), "last_error": result.get("error")})
        flushed = {"batch": batch, "result": result}
    else:
        write_heartbeat(src, extra={"pending": len(coalescer.pending)})
    return current, flushed


def cmd_status(args) -> int:
    root = Path(args.src or os.environ.get("SECOND_BRAIN_ROOT") or "").expanduser()
    print(json.dumps({"ok": True, "watcher": read_heartbeat(root, stale_after=args.stale_after), "root": str(root)}))
    return 0


def cmd_flush(args) -> int:
    """Test/operator helper: note nothing, push whatever is pending or the whole tree once."""
    dest = dest_from_env()
    if not dest:
        print(json.dumps({"error": "destination required", "hint": "OKF_REPLICA_DEST — never a hard-coded remote"}))
        return 1
    src = Path(args.src or os.environ.get("SECOND_BRAIN_ROOT") or "").expanduser()
    coalescer = Coalescer(debounce_s=0)
    current = scan_mtimes(src)
    for rel in current:
        coalescer.note(rel, 0)
    batch = coalescer.take()
    result = dispatch_push(src, batch, exclude_telemetry=args.exclude_telemetry, replica_id=args.replica_id)
    write_heartbeat(src, extra={"last_batch": len(batch), "last_ok": result.get("ok")})
    print(json.dumps({"ok": result.get("ok"), "batch": len(batch), "result": result}))
    return 0 if result.get("ok") else 1


def cmd_run(args) -> int:
    dest = dest_from_env()
    if not dest:
        print(json.dumps({"error": "destination required", "hint": "OKF_REPLICA_DEST — never a hard-coded remote"}))
        return 1
    src = Path(args.src or os.environ.get("SECOND_BRAIN_ROOT") or "").expanduser()
    if not src.exists():
        print(json.dumps({"error": "source does not exist", "src": str(src)}))
        return 1
    coalescer = Coalescer(debounce_s=args.debounce)
    previous: dict[str, float] = {}
    write_heartbeat(src, extra={"transport": "s3-push" if dest.startswith("s3://") else "rsync-push"})
    print(json.dumps({"ok": True, "watching": str(src), "dest": dest, "debounce_s": args.debounce}), flush=True)
    try:
        while True:
            previous, flushed = watch_once(
                src,
                coalescer,
                previous,
                exclude_telemetry=args.exclude_telemetry,
                replica_id=args.replica_id,
            )
            if flushed:
                print(json.dumps({"flushed": len(flushed["batch"]), "ok": flushed["result"].get("ok")}), flush=True)
            time.sleep(args.poll)
    except KeyboardInterrupt:
        write_heartbeat(src, extra={"alive": False, "error": "watcher stopped"})
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", nargs="?", default="run", choices=["run", "status", "flush"])
    p.add_argument("--src", default="")
    p.add_argument("--replica-id", default="")
    p.add_argument("--debounce", type=float, default=DEFAULT_DEBOUNCE)
    p.add_argument("--poll", type=float, default=0.25)
    p.add_argument("--stale-after", type=float, default=STALE_AFTER)
    p.add_argument("--exclude-telemetry", action="store_true")
    args = p.parse_args(argv if argv is not None else None)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "flush":
        return cmd_flush(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
