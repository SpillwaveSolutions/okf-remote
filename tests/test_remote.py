#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP = ROOT / "scripts" / "remote_mcp.py"
RSYNC = ROOT / "scripts" / "remote_rsync.py"
WATCH = ROOT / "scripts" / "remote_watch.py"
TS_SAMPLE = ROOT.parent / "okf-time-series" / "sample-knowledge"
PTR_SAMPLE = ROOT.parent / "okf-pointers" / "sample-knowledge"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from remote_auth import AuthError, b64url_encode, validate_token  # noqa: E402
from remote_watch import Coalescer, read_heartbeat, watch_once, write_heartbeat  # noqa: E402


def mcp(*args):
    return subprocess.run([sys.executable, str(MCP), *args], capture_output=True, text=True)


class TestRemote(unittest.TestCase):
    def test_forbidden_verbs(self):
        for v in ("summarize", "compact", "saliency_detect", "write_session", "agentic_search"):
            r = mcp(v)
            self.assertNotEqual(r.returncode, 0, v)
            self.assertIn("not allowed", r.stdout)

    def test_replica_status_uninitialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = mcp("replica_status", "--root", tmp)
            self.assertEqual(r.returncode, 0)
            data = json.loads(r.stdout)
            self.assertTrue(data["ok"])

    def test_pull_copytree_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            src.mkdir()
            (src / "okf").mkdir()
            (src / "okf" / "hello.md").write_text("# hi\n", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(RSYNC), "--src", str(src), "--dest", str(dest), "--replica-id", "northstar-dev-01"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((dest / "okf" / "hello.md").exists())
            st = mcp("replica_status", "--root", str(dest))
            self.assertEqual(st.returncode, 0)
            man = json.loads(st.stdout)
            self.assertEqual(man["replica_id"], "northstar-dev-01")

    def test_walk_chronological_on_time_series_sample(self):
        if not TS_SAMPLE.exists():
            self.skipTest("okf-time-series sample not next door")
        r = mcp("walk_chronological", "--root", str(TS_SAMPLE))
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["engine"], "filesystem")
        types = {n["type"] for n in data["nodes"]}
        self.assertIn("temporal.session", types)
        self.assertIn("temporal.year", types)
        paths = [n["path"] for n in data["nodes"]]
        self.assertTrue(any("software_engineer__atlas__001.md" in p for p in paths))
        self.assertFalse(any(".telemetry.md" in p for p in paths))

    def test_get_node_refuses_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = mcp("get_node", "--root", tmp, "--path", "../etc/passwd")
            self.assertNotEqual(r.returncode, 0)

    def test_query_is_cursor_paginated(self):
        if not TS_SAMPLE.exists():
            self.skipTest("okf-time-series sample not next door")
        first = mcp("query", "--root", str(TS_SAMPLE), "--path", "okf/temporal", "--limit", "3")
        self.assertEqual(first.returncode, 0, first.stdout)
        page1 = json.loads(first.stdout)
        self.assertEqual(page1["pagination"], "cursor")
        self.assertEqual(len(page1["items"]), 3)
        self.assertTrue(page1["next_cursor"])
        second = mcp(
            "query",
            "--root",
            str(TS_SAMPLE),
            "--path",
            "okf/temporal",
            "--limit",
            "3",
            "--cursor",
            page1["next_cursor"],
        )
        self.assertEqual(second.returncode, 0, second.stdout)
        page2 = json.loads(second.stdout)
        self.assertEqual(len(page2["items"]), 3)
        paths1 = {i["path"] for i in page1["items"]}
        paths2 = {i["path"] for i in page2["items"]}
        self.assertFalse(paths1 & paths2)
        self.assertGreater(min(paths2), max(paths1))

    def test_query_type_filter(self):
        if not TS_SAMPLE.exists():
            self.skipTest("okf-time-series sample not next door")
        r = mcp("query", "--root", str(TS_SAMPLE), "--type", "temporal.session", "--limit", "50")
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertTrue(data["items"])
        self.assertTrue(all(i["type"] == "temporal.session" for i in data["items"]))
        self.assertIsNone(data["next_cursor"])

    def test_reverse_pointers_returns_inverse(self):
        if not PTR_SAMPLE.exists():
            self.skipTest("okf-pointers sample not next door")
        r = mcp("reverse_pointers", "--root", str(PTR_SAMPLE), "--query", "2026-W34")
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["engine"], "scan")
        self.assertTrue(data["hits"])
        inbound = [h for h in data["hits"] if h.get("direction") == "in"]
        self.assertTrue(inbound)
        self.assertEqual(inbound[0]["link_type"], "start_of")
        self.assertEqual(inbound[0]["written_as"], "started_in")
        self.assertEqual(inbound[0]["other"], "epic_alpha_01")

    def test_query_is_allowed(self):
        r = mcp("query", "--root", tempfile.mkdtemp())
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["pagination"], "cursor")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def mint_hs256(secret: bytes, payload: dict, kid: str = "n1") -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    body = _b64url(json.dumps(payload).encode())
    sig = hmac.new(secret, f"{header}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


class TestRev3PushAndAuth(unittest.TestCase):
    def test_push_missing_dest_is_clean_error(self):
        env = os.environ.copy()
        env.pop("OKF_REPLICA_DEST", None)
        r = subprocess.run(
            [sys.executable, str(RSYNC), "push", "--src", "/tmp"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("OKF_REPLICA_DEST", data["hint"])
        self.assertNotIn("github.com", r.stdout)

    def test_push_copies_and_excludes_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            (src / "okf").mkdir(parents=True)
            (src / "okf" / "hello.md").write_text("# hi\n", encoding="utf-8")
            (src / "okf" / "x.telemetry.md").write_text("secret\n", encoding="utf-8")
            env = os.environ.copy()
            env["OKF_REPLICA_DEST"] = str(dest)
            r = subprocess.run(
                [sys.executable, str(RSYNC), "push", "--src", str(src), "--exclude-telemetry", "--replica-id", "northstar-dev-01"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((dest / "okf" / "hello.md").exists())
            self.assertFalse((dest / "okf" / "x.telemetry.md").exists())

    def test_ten_files_one_batch(self):
        coal = Coalescer(debounce_s=2)
        for i in range(10):
            coal.note(f"okf/f{i}.md", now_ts=100.0)
        self.assertFalse(coal.due(100.5))
        self.assertTrue(coal.due(102.0))
        batch = coal.take()
        self.assertEqual(len(batch), 10)
        self.assertEqual(len(coal.take()), 0)

    def test_watch_once_flushes_one_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            (src / "okf").mkdir(parents=True)
            dest.mkdir()
            os.environ["OKF_REPLICA_DEST"] = str(dest)
            self.addCleanup(lambda: os.environ.pop("OKF_REPLICA_DEST", None))
            for i in range(10):
                (src / "okf" / f"f{i}.md").write_text(f"{i}\n", encoding="utf-8")
            coal = Coalescer(debounce_s=0)
            current, flushed = watch_once(src, coal, {}, exclude_telemetry=False, replica_id="northstar-dev-01", now_ts=1.0)
            self.assertIsNotNone(flushed)
            self.assertEqual(len(flushed["batch"]), 10)
            self.assertTrue(flushed["result"]["ok"])
            self.assertTrue((dest / "okf" / "f0.md").exists())
            self.assertTrue((dest / "okf" / "f9.md").exists())

    def test_watcher_death_visible_on_replica_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_heartbeat(root)
            live = read_heartbeat(root, stale_after=10)
            self.assertTrue(live["alive"])
            hb = root / ".okf-watcher-heartbeat.json"
            os.utime(hb, (time.time() - 30, time.time() - 30))
            dead = read_heartbeat(root, stale_after=10)
            self.assertFalse(dead["alive"])
            self.assertIn("stale", dead["error"])
            st = mcp("replica_status", "--root", str(root))
            self.assertEqual(st.returncode, 0, st.stdout)
            data = json.loads(st.stdout)
            self.assertFalse(data["watcher"]["alive"])

    def test_stdio_unauthenticated_still_works(self):
        r = mcp("replica_status", "--root", tempfile.mkdtemp())
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(json.loads(r.stdout)["ok"])

    def test_bind_without_issuer_is_startup_error(self):
        env = os.environ.copy()
        for key in ("OKF_MCP_ISSUER", "OKF_MCP_AUDIENCE", "OKF_MCP_JWKS"):
            env.pop(key, None)
        r = subprocess.run(
            [sys.executable, str(MCP), "serve", "--bind", "127.0.0.1:0"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("issuer", r.stdout)

    def test_non_loopback_bind_requires_tls(self):
        secret = b"northstar-test-secret"
        with tempfile.TemporaryDirectory() as tmp:
            jwks_path = Path(tmp) / "jwks.json"
            jwks_path.write_text(
                json.dumps({"keys": [{"kty": "oct", "kid": "n1", "alg": "HS256", "k": _b64url(secret)}]}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["OKF_MCP_ISSUER"] = "https://auth.northstar.example"
            env["OKF_MCP_AUDIENCE"] = "okf-remote"
            env["OKF_MCP_JWKS"] = str(jwks_path)
            env.pop("OKF_MCP_TLS_CERT", None)
            env.pop("OKF_MCP_TLS_KEY", None)
            r = subprocess.run(
                [sys.executable, str(MCP), "serve", "--bind", "0.0.0.0:18766"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("TLS", r.stdout)

    def test_token_validation_cases(self):
        secret = b"northstar-test-secret"
        with tempfile.TemporaryDirectory() as tmp:
            jwks_path = Path(tmp) / "jwks.json"
            jwks_path.write_text(
                json.dumps({"keys": [{"kty": "oct", "kid": "n1", "alg": "HS256", "k": _b64url(secret)}]}),
                encoding="utf-8",
            )
            cfg = {"issuer": "https://auth.northstar.example", "audience": "okf-remote", "jwks": str(jwks_path)}
            good = mint_hs256(secret, {"iss": cfg["issuer"], "aud": cfg["audience"], "exp": int(time.time()) + 60})
            self.assertEqual(validate_token(good, cfg)["iss"], cfg["issuer"])
            expired = mint_hs256(secret, {"iss": cfg["issuer"], "aud": cfg["audience"], "exp": int(time.time()) - 10})
            with self.assertRaises(AuthError):
                validate_token(expired, cfg)
            wrong_aud = mint_hs256(secret, {"iss": cfg["issuer"], "aud": "someone-else", "exp": int(time.time()) + 60})
            with self.assertRaises(AuthError):
                validate_token(wrong_aud, cfg)
            with self.assertRaises(AuthError):
                validate_token("", cfg)

    def test_network_rejects_bad_token_and_write_verbs(self):
        secret = b"northstar-test-secret"
        with tempfile.TemporaryDirectory() as tmp:
            jwks_path = Path(tmp) / "jwks.json"
            jwks_path.write_text(
                json.dumps({"keys": [{"kty": "oct", "kid": "n1", "alg": "HS256", "k": _b64url(secret)}]}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["OKF_MCP_ISSUER"] = "https://auth.northstar.example"
            env["OKF_MCP_AUDIENCE"] = "okf-remote"
            env["OKF_MCP_JWKS"] = str(jwks_path)
            proc = subprocess.Popen(
                [sys.executable, str(MCP), "serve", "--bind", "127.0.0.1:18765", "--root", tmp],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            def _stop():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

            self.addCleanup(_stop)
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    urllib.request.urlopen("http://127.0.0.1:18765/", timeout=0.2)
                except urllib.error.HTTPError:
                    break
                except OSError:
                    time.sleep(0.05)
            url = "http://127.0.0.1:18765/"

            def post(token, payload):
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        return resp.status, json.loads(resp.read().decode())
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read().decode())

            self.assertEqual(post("", {"verb": "query"})[0], 401)
            expired = mint_hs256(secret, {"iss": env["OKF_MCP_ISSUER"], "aud": env["OKF_MCP_AUDIENCE"], "exp": int(time.time()) - 5})
            self.assertEqual(post(expired, {"verb": "query"})[0], 401)
            good = mint_hs256(secret, {"iss": env["OKF_MCP_ISSUER"], "aud": env["OKF_MCP_AUDIENCE"], "exp": int(time.time()) + 60})
            status, body = post(good, {"verb": "query", "path": "okf"})
            self.assertEqual(status, 200, body)
            self.assertTrue(body.get("ok"))
            status, body = post(good, {"verb": "write_session"})
            self.assertNotEqual(status, 200)
            self.assertIn("not allowed", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
