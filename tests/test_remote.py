#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP = ROOT / "scripts" / "remote_mcp.py"
RSYNC = ROOT / "scripts" / "remote_rsync.py"
TS_SAMPLE = ROOT.parent / "okf-time-series" / "sample-knowledge"


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


if __name__ == "__main__":
    unittest.main()
