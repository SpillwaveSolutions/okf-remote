#!/usr/bin/env python3
"""Pull-based replica. rsync first. Never invents a remote URL.

Default is a dry-run of `rsync -a` without --delete. Conflict policy is an
open question on okf-plugin#74 and is not silently answered.

S3 is a consumer-side daemon pulling objects to local disk (docs/S3.md), then
this helper (or the daemon's own copy) lands them at $OKF_REPLICA_ROOT. Direct
bucket walking is not the documented path.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_pull(args) -> int:
    src = Path(args.src or os.environ.get("SECOND_BRAIN_ROOT") or "").expanduser()
    dest = Path(args.dest or os.environ.get("OKF_REPLICA_ROOT") or "").expanduser()
    if not src or not dest:
        print(json.dumps({"error": "src and dest required", "hint": "SECOND_BRAIN_ROOT and OKF_REPLICA_ROOT — never a hard-coded remote"}))
        return 1
    if not src.exists():
        print(json.dumps({"error": "source does not exist", "src": str(src)}))
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    rsync = shutil.which("rsync")
    cmd = None
    if rsync:
        cmd = [rsync, "-a"]
        if args.exclude_telemetry:
            cmd += ["--exclude", "*.telemetry.md", "--exclude", "*.telemetry_*.md"]
        if args.delete:
            # Not the default. --delete is a policy choice, see #74.
            cmd.append("--delete")
        if args.dry_run:
            cmd.append("--dry-run")
        cmd += [str(src) + "/", str(dest) + "/"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(json.dumps({"ok": False, "error": proc.stderr.strip(), "cmd": cmd}))
            return proc.returncode
    else:
        # Filesystem copy fallback when rsync is not on PATH (CI).
        if not args.dry_run:
            for p in src.rglob("*"):
                rel = p.relative_to(src)
                if args.exclude_telemetry and ("telemetry" in p.name):
                    continue
                target = dest / rel
                if p.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, target)
        cmd = ["copytree-fallback", str(src), str(dest)]
    if not args.dry_run:
        manifest = {
            "schema": "okf.replica.manifest/v0",
            "replica_id": args.replica_id or os.environ.get("OKF_REPLICA_ID") or dest.name,
            "source_fingerprint": f"path:{src}",
            "synced_at": now(),
            "root": str(dest),
            "includes_telemetry": not args.exclude_telemetry,
        }
        (dest / "replica.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "src": str(src), "dest": str(dest), "dry_run": bool(args.dry_run), "cmd": cmd}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="")
    p.add_argument("--dest", default="")
    p.add_argument("--replica-id", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delete", action="store_true", help="NOT default. Open question on #74.")
    p.add_argument("--exclude-telemetry", action="store_true")
    return cmd_pull(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
