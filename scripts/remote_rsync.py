#!/usr/bin/env python3
"""Replica transport. Push is the documented default. Pull is a backstop.

Destination from $OKF_REPLICA_DEST (or --dest). Never a hard-coded host,
bucket, or git URL. No --delete by default.

S3: $OKF_REPLICA_DEST starting with s3:// is an object put. The consumer-side
daemon pulling objects to local disk is unchanged (docs/S3.md).
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


def require_dest(raw: str) -> str:
    dest = (raw or os.environ.get("OKF_REPLICA_DEST") or "").strip()
    if not dest:
        print(
            json.dumps(
                {
                    "error": "destination required",
                    "hint": "OKF_REPLICA_DEST — never a hard-coded remote",
                }
            )
        )
        return ""
    return dest


def _exclude_ok(path: Path, exclude_telemetry: bool) -> bool:
    if not exclude_telemetry:
        return True
    name = path.name
    return not (name.endswith(".telemetry.md") or ".telemetry_" in name)


def rsync_or_copy(src: Path, dest: str, *, exclude_telemetry: bool, delete: bool, dry_run: bool, paths: list[str] | None = None) -> tuple[int, list[str]]:
    """Push/pull files. `dest` is a filesystem path or user@host:path. Never invented."""
    rsync = shutil.which("rsync")
    cmd: list[str]
    if rsync:
        cmd = [rsync, "-a"]
        if exclude_telemetry:
            cmd += ["--exclude", "*.telemetry.md", "--exclude", "*.telemetry_*.md"]
        if delete:
            cmd.append("--delete")
        if dry_run:
            cmd.append("--dry-run")
        if paths:
            cmd.append("--files-from=-")
            cmd += [str(src) + "/", dest.rstrip("/") + "/"]
            proc = subprocess.run(cmd, input="\n".join(paths) + "\n", capture_output=True, text=True)
        else:
            cmd += [str(src) + "/", dest.rstrip("/") + "/"]
            proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(json.dumps({"ok": False, "error": proc.stderr.strip(), "cmd": cmd}))
            return proc.returncode, cmd
        return 0, cmd

    if ":" in dest and not Path(dest).exists() and not dest.startswith("/"):
        print(json.dumps({"ok": False, "error": "rsync required for host:path destinations"}))
        return 1, ["rsync-missing"]

    dest_path = Path(dest).expanduser()
    dest_path.mkdir(parents=True, exist_ok=True)
    cmd = ["copytree-fallback", str(src), str(dest_path)]
    if dry_run:
        return 0, cmd
    selected = [Path(p) for p in paths] if paths else None
    if selected is not None:
        for rel in selected:
            p = src / rel
            if not p.exists() or p.is_dir():
                if p.is_dir():
                    (dest_path / rel).mkdir(parents=True, exist_ok=True)
                continue
            if not _exclude_ok(p, exclude_telemetry):
                continue
            target = dest_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
        return 0, cmd
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if not _exclude_ok(p, exclude_telemetry):
            continue
        target = dest_path / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    return 0, cmd


def write_manifest(dest: Path, replica_id: str, src: Path, includes_telemetry: bool, extra: dict | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "okf.replica.manifest/v0",
        "replica_id": replica_id or os.environ.get("OKF_REPLICA_ID") or dest.name,
        "source_fingerprint": f"path:{src}",
        "synced_at": now(),
        "root": str(dest),
        "includes_telemetry": includes_telemetry,
        "mode": extra.get("mode") if extra else "pull",
    }
    if extra:
        manifest.update(extra)
    (dest / "replica.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def s3_push(src: Path, dest: str, *, exclude_telemetry: bool, dry_run: bool) -> int:
    """Put objects. Destination is s3://bucket/prefix from the environment. Never invented."""
    if not dest.startswith("s3://"):
        print(json.dumps({"error": "s3 dest must be s3://bucket/prefix from OKF_REPLICA_DEST"}))
        return 1
    aws = shutil.which("aws")
    if aws:
        cmd = [aws, "s3", "sync", str(src) + "/", dest]
        if exclude_telemetry:
            cmd += ["--exclude", "*.telemetry.md", "--exclude", "*.telemetry_*.md"]
        if dry_run:
            cmd.append("--dryrun")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(json.dumps({"ok": False, "error": proc.stderr.strip(), "cmd": cmd}))
            return proc.returncode
        print(json.dumps({"ok": True, "transport": "s3-push", "src": str(src), "dest": dest, "dry_run": dry_run, "cmd": cmd}))
        return 0
    try:
        import boto3  # type: ignore
    except ImportError:
        print(json.dumps({"ok": False, "error": "s3 push needs aws CLI or boto3 — neither is present"}))
        return 1
    rest = dest[len("s3://") :]
    bucket, _, prefix = rest.partition("/")
    if not bucket:
        print(json.dumps({"error": "s3 dest missing bucket"}))
        return 1
    client = boto3.client("s3")
    uploaded = []
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        if not _exclude_ok(p, exclude_telemetry):
            continue
        key = f"{prefix.rstrip('/')}/{p.relative_to(src)}" if prefix else str(p.relative_to(src))
        uploaded.append(key)
        if not dry_run:
            client.upload_file(str(p), bucket, key)
    print(json.dumps({"ok": True, "transport": "s3-push", "src": str(src), "dest": dest, "dry_run": dry_run, "uploaded": len(uploaded)}))
    return 0


def cmd_pull(args) -> int:
    src = Path(args.src or os.environ.get("SECOND_BRAIN_ROOT") or "").expanduser()
    dest_s = args.dest or os.environ.get("OKF_REPLICA_ROOT") or ""
    if not str(src) or not dest_s:
        print(json.dumps({"error": "src and dest required", "hint": "SECOND_BRAIN_ROOT and OKF_REPLICA_ROOT — never a hard-coded remote"}))
        return 1
    if not src.exists():
        print(json.dumps({"error": "source does not exist", "src": str(src)}))
        return 1
    dest = Path(dest_s).expanduser()
    rc, cmd = rsync_or_copy(src, str(dest), exclude_telemetry=args.exclude_telemetry, delete=args.delete, dry_run=args.dry_run)
    if rc != 0:
        return rc
    if not args.dry_run:
        write_manifest(dest, args.replica_id, src, not args.exclude_telemetry, extra={"mode": "pull"})
    print(json.dumps({"ok": True, "mode": "pull", "src": str(src), "dest": str(dest), "dry_run": bool(args.dry_run), "cmd": cmd}))
    return 0


def cmd_push(args) -> int:
    dest = require_dest(args.dest)
    if not dest:
        return 1
    src = Path(args.src or os.environ.get("SECOND_BRAIN_ROOT") or "").expanduser()
    if not str(src) or not src.exists():
        print(json.dumps({"error": "source does not exist", "hint": "SECOND_BRAIN_ROOT — never a hard-coded remote", "src": str(src)}))
        return 1
    if dest.startswith("s3://"):
        return s3_push(src, dest, exclude_telemetry=args.exclude_telemetry, dry_run=args.dry_run)
    rc, cmd = rsync_or_copy(
        src,
        dest,
        exclude_telemetry=args.exclude_telemetry,
        delete=args.delete,
        dry_run=args.dry_run,
        paths=args.paths or None,
    )
    if rc != 0:
        return rc
    dest_path = Path(dest).expanduser()
    if not args.dry_run and dest_path.exists():
        write_manifest(
            dest_path,
            args.replica_id,
            src,
            not args.exclude_telemetry,
            extra={"mode": "push", "transport": "rsync-push"},
        )
    print(json.dumps({"ok": True, "mode": "push", "src": str(src), "dest": dest, "dry_run": bool(args.dry_run), "cmd": cmd, "batched": len(args.paths or [])}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode")

    def add_common(sp):
        sp.add_argument("--src", default="")
        sp.add_argument("--dest", default="")
        sp.add_argument("--replica-id", default="")
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--delete", action="store_true", help="NOT default. Open question on #74.")
        sp.add_argument("--exclude-telemetry", action="store_true")

    pull = sub.add_parser("pull", help="Backstop. Documented default is push.")
    add_common(pull)
    push = sub.add_parser("push", help="Push to $OKF_REPLICA_DEST. Documented default.")
    add_common(push)
    push.add_argument("--paths", nargs="*", default=[])
    # Legacy flags (no subcommand) stay pull so 0.2.0 callers keep working.
    add_common(p)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = build_parser()
    args = p.parse_args(argv)
    mode = args.mode or "pull"
    if mode == "push":
        return cmd_push(args)
    return cmd_pull(args)


if __name__ == "__main__":
    sys.exit(main())
