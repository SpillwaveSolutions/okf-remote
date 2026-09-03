#!/usr/bin/env python3
"""Read-only verb table for okf-remote.

stdio-only. No bind address. No write or processing verbs.
agentic_search is a skill, not a verb (open question on #74).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = {
    "list_nodes",
    "get_node",
    "walk_chronological",
    "reverse_pointers",
    "replica_status",
}
FORBIDDEN_EXACT = {"summarize", "compact", "saliency_detect", "agentic_search"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def replica_root(raw: str | None) -> Path:
    value = (raw or os.environ.get("OKF_REPLICA_ROOT") or os.environ.get("SECOND_BRAIN_ROOT") or "knowledge").strip()
    return Path(value)


def refuse(verb: str) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "error": "verb not allowed on a read-only remote",
                "verb": verb,
                "allowed": sorted(ALLOWED),
            }
        )
    )
    return 1


def cmd_invoke(args) -> int:
    verb = args.verb
    if verb.startswith("write") or verb in FORBIDDEN_EXACT or verb not in ALLOWED:
        return refuse(verb)
    root = replica_root(args.root)
    if verb == "replica_status":
        manifest = root / "replica.manifest.json"
        if manifest.exists():
            print(manifest.read_text(encoding="utf-8"))
            return 0
        print(
            json.dumps(
                {
                    "ok": True,
                    "schema": "okf.replica.manifest/v0",
                    "replica_id": "uninitialized",
                    "synced_at": None,
                    "root": str(root),
                }
            )
        )
        return 0
    if verb == "list_nodes":
        base = root / (args.path or "okf")
        if not base.exists():
            print(json.dumps({"ok": True, "entries": []}))
            return 0
        entries = sorted(p.name for p in base.iterdir())
        print(json.dumps({"ok": True, "path": str(base), "entries": entries}))
        return 0
    if verb == "get_node":
        target = root / args.path
        if not target.exists() or not target.is_file():
            print(json.dumps({"ok": False, "error": "not found", "path": args.path}))
            return 1
        print(json.dumps({"ok": True, "path": args.path, "text": target.read_text(encoding="utf-8")}))
        return 0
    if verb == "walk_chronological":
        year = root / "okf" / "temporal"
        years = sorted(p.name for p in year.glob("*") if p.is_dir()) if year.exists() else []
        print(json.dumps({"ok": True, "years": years, "note": "summaries only; open a year file with get_node"}))
        return 0
    if verb == "reverse_pointers":
        ptr = root / "okf" / "pointers"
        q = args.query or ""
        hits = []
        if ptr.exists() and q:
            for p in ptr.glob("*.md"):
                if q in p.name:
                    hits.append(p.name)
        print(json.dumps({"ok": True, "query": q, "hits": hits, "engine": "scan"}))
        return 0
    return refuse(verb)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("verb")
    p.add_argument("--root", default="")
    p.add_argument("--path", default="")
    p.add_argument("--query", default="")
    args = p.parse_args()
    return cmd_invoke(args)


if __name__ == "__main__":
    sys.exit(main())
