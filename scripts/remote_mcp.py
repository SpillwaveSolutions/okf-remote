#!/usr/bin/env python3
"""Read-only verb table for okf-remote.

stdio is the default transport and is unauthenticated. When a bind address is
configured the server is an OAuth 2.1 / OIDC resource server: it validates
incoming tokens and nothing more. Token issuance belongs to a separate
authorization server. Binding without OKF_MCP_ISSUER is a startup error.

agentic_search is a skill (AGER), not a verb. Its model is configured per
deployment via OKF_AGENTIC_SEARCH_MODEL — never pinned in this plugin.

query is cursor-paginated. Offsets drift under concurrent writes; a cursor is
the last path returned.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from remote_watch import read_heartbeat  # noqa: E402

ALLOWED = {
    "list_nodes",
    "get_node",
    "walk_chronological",
    "reverse_pointers",
    "replica_status",
    "query",
}
FORBIDDEN_EXACT = {"summarize", "compact", "saliency_detect", "agentic_search"}
ARTIFACT = (".telemetry.md", ".summary.md", ".saliency.md")

# Fallback inverse map matching okf-pointers taxonomy v1.0.0.
# Reverse traversal returns the inverse name. Do not invent values.
INVERSES = {
    "contains": "contained_by",
    "contained_by": "contains",
    "started_in": "start_of",
    "start_of": "started_in",
    "ended_in": "end_of",
    "end_of": "ended_in",
    "precedes": "follows",
    "follows": "precedes",
    "scheduled_for": "scheduled",
    "scheduled": "scheduled_for",
    "references": "referenced_by",
    "referenced_by": "references",
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


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


def _frontmatter(text: str) -> dict:
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    parts = text.split("---", 2)
    if len(parts) < 3:
        return meta
    for line in parts[1].splitlines():
        if ":" in line and not line.startswith(" ") and not line.strip().startswith("-"):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("'\"")
    return meta


def _frontmatter_type_title(text: str) -> tuple[str, str, str]:
    meta = _frontmatter(text)
    return meta.get("type", ""), meta.get("title", ""), meta.get("period", "")


def encode_cursor(path: str) -> str:
    return base64.urlsafe_b64encode(path.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except Exception:
        return cursor


def iter_md(root: Path, prefix: str = "okf"):
    base = root / prefix.lstrip("/")
    if not base.exists():
        return
    if base.is_file():
        yield base
        return
    for p in sorted(base.rglob("*.md")):
        yield p


def walk_chronological(root: Path) -> list[dict]:
    """Filesystem walk. No BM25, no vectors, no graph index."""
    temporal = root / "okf" / "temporal"
    nodes: list[dict] = []
    if not temporal.exists():
        return nodes
    for p in sorted(temporal.rglob("*.md")):
        if p.name == "index.md" or p.name.endswith(ARTIFACT):
            continue
        text = p.read_text(encoding="utf-8")
        typ, title, period = _frontmatter_type_title(text)
        rel = str(p.relative_to(root)).replace("\\", "/")
        nodes.append(
            {
                "path": "/" + rel,
                "type": typ,
                "title": title or p.stem,
                "period": period,
            }
        )
    return nodes


def cmd_query(root: Path, path: str, typ: str, cursor: str, limit: int) -> int:
    prefix = (path or "okf").lstrip("/")
    items = []
    for p in iter_md(root, prefix) or []:
        if p.name.endswith(ARTIFACT):
            continue
        text = p.read_text(encoding="utf-8")
        fm_type, title, period = _frontmatter_type_title(text)
        if typ and fm_type != typ:
            continue
        rel = "/" + str(p.relative_to(root)).replace("\\", "/")
        items.append({"path": rel, "type": fm_type, "title": title or p.stem, "period": period})
    items.sort(key=lambda n: n["path"])
    after = decode_cursor(cursor) if cursor else ""
    if after:
        items = [n for n in items if n["path"] > after]
    page = items[:limit]
    next_cursor = encode_cursor(page[-1]["path"]) if len(items) > limit else None
    print(
        json.dumps(
            {
                "ok": True,
                "engine": "filesystem",
                "pagination": "cursor",
                "items": page,
                "next_cursor": next_cursor,
                "limit": limit,
            }
        )
    )
    return 0


def reverse_pointers(root: Path, query: str) -> dict:
    ptr = root / "okf" / "pointers"
    hits = []
    if ptr.exists() and query:
        for p in sorted(ptr.glob("*.md")):
            if p.name == "index.md":
                continue
            text = p.read_text(encoding="utf-8")
            meta = _frontmatter(text)
            if meta.get("type") != "pointer.link":
                # filename scan fallback for catalogs that only have grep bait
                if query in p.name:
                    hits.append({"file": p.name, "engine": "filename"})
                continue
            src = meta.get("source", "")
            dest = meta.get("destination", "")
            lt = meta.get("link_type", "")
            rel = "/" + str(p.relative_to(root)).replace("\\", "/")
            if src == query:
                hits.append(
                    {
                        "file": rel,
                        "direction": "out",
                        "link_type": lt,
                        "other": dest,
                        "other_type": meta.get("destination_type"),
                    }
                )
            if dest == query:
                hits.append(
                    {
                        "file": rel,
                        "direction": "in",
                        "link_type": INVERSES.get(lt),
                        "written_as": lt,
                        "other": src,
                        "other_type": meta.get("source_type"),
                    }
                )
    return {"ok": True, "query": query, "hits": hits, "engine": "scan"}


def cmd_invoke(args) -> int:
    verb = args.verb
    if verb.startswith("write") or verb in FORBIDDEN_EXACT or verb not in ALLOWED:
        return refuse(verb)
    root = replica_root(args.root)
    if verb == "replica_status":
        manifest = root / "replica.manifest.json"
        watcher = read_heartbeat(root)
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["watcher"] = watcher
            print(json.dumps(data))
            return 0
        print(
            json.dumps(
                {
                    "ok": True,
                    "schema": "okf.replica.manifest/v0",
                    "replica_id": "uninitialized",
                    "synced_at": None,
                    "root": str(root),
                    "watcher": watcher,
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
        if not args.path:
            print(json.dumps({"ok": False, "error": "path required"}))
            return 1
        rel = args.path.lstrip("/")
        target = (root / rel).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            print(json.dumps({"ok": False, "error": "path escapes replica"}))
            return 1
        if not target.exists() or not target.is_file():
            print(json.dumps({"ok": False, "error": "not found", "path": args.path}))
            return 1
        print(json.dumps({"ok": True, "path": args.path, "text": target.read_text(encoding="utf-8")}))
        return 0
    if verb == "walk_chronological":
        nodes = walk_chronological(root)
        print(json.dumps({"ok": True, "engine": "filesystem", "nodes": nodes, "note": "metadata only; open a file with get_node"}))
        return 0
    if verb == "query":
        limit = args.limit if args.limit else DEFAULT_LIMIT
        if limit < 1:
            limit = 1
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        return cmd_query(root, args.path, args.type, args.cursor, limit)
    if verb == "reverse_pointers":
        print(json.dumps(reverse_pointers(root, args.query or "")))
        return 0
    return refuse(verb)


def _ns(**kw):
    class N:
        pass

    n = N()
    n.verb = kw.get("verb", "")
    n.root = kw.get("root", "")
    n.path = kw.get("path", "")
    n.query = kw.get("query", "")
    n.cursor = kw.get("cursor", "")
    n.limit = int(kw.get("limit") or 0)
    n.type = kw.get("type", "")
    return n


def cmd_serve(argv: list[str]) -> int:
    """Network path. Auth gates access; it does not add verbs."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from remote_auth import AuthError, require_bind_config, validate_token

    p = argparse.ArgumentParser(prog="remote_mcp.py serve")
    p.add_argument("--bind", required=True, help="host:port. No anonymous bind.")
    p.add_argument("--root", default="")
    args = p.parse_args(argv)
    try:
        cfg = require_bind_config()
    except AuthError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    host, _, port_s = args.bind.rpartition(":")
    if not host or not port_s:
        print(json.dumps({"ok": False, "error": "bind must be host:port"}))
        return 1
    port = int(port_s)
    root = args.root

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):  # noqa: A003
            return

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            auth = self.headers.get("Authorization") or ""
            if not auth.startswith("Bearer "):
                self._send(401, {"ok": False, "error": "missing bearer token"})
                return
            try:
                validate_token(auth[len("Bearer ") :].strip(), cfg)
            except AuthError as exc:
                self._send(exc.status if exc.status >= 400 else 401, {"ok": False, "error": str(exc)})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"ok": False, "error": "invalid json"})
                return
            verb = str(body.get("verb") or "")
            ns = _ns(
                verb=verb,
                root=body.get("root") or root,
                path=body.get("path") or "",
                query=body.get("query") or "",
                cursor=body.get("cursor") or "",
                limit=body.get("limit") or 0,
                type=body.get("type") or "",
            )
            from io import StringIO

            buf = StringIO()
            old = sys.stdout
            sys.stdout = buf
            try:
                rc = cmd_invoke(ns)
            finally:
                sys.stdout = old
            raw = buf.getvalue() or "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"ok": rc == 0, "raw": raw}
            self._send(200 if rc == 0 else 403, payload)

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(json.dumps({"ok": True, "bind": args.bind, "issuer": cfg["issuer"], "transport": "network"}))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return cmd_serve(argv[1:])
    p = argparse.ArgumentParser()
    p.add_argument("verb")
    p.add_argument("--root", default="")
    p.add_argument("--path", default="")
    p.add_argument("--query", default="")
    p.add_argument("--cursor", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--type", default="")
    args = p.parse_args(argv)
    return cmd_invoke(args)


if __name__ == "__main__":
    sys.exit(main())
