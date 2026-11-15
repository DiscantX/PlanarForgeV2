"""Tests for the MCP server (tools/mcp_server). No game installation is needed."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.mcp_server import diagnostics, tool_registry
from tools.mcp_server.shim import Supervisor, WorkerError, source_fingerprint

SHIM = REPO_ROOT / "tools" / "mcp_server" / "shim.py"


class DiagnosticsTests(unittest.TestCase):
    def test_builds_allowed_commands(self):
        command = diagnostics.build_command(
            "test_suite", ["--test", "2", "--schema", "ARE", "--game", "BG2EE,IWDEE",
                           "--audit-gaps"], python="py")
        self.assertEqual(command[:2], ["py", "tools/tests/test_suite.py"])
        self.assertIn("--no-progress", command)
        self.assertEqual(command[command.index("--game") + 1], "BG2EE,IWDEE")

    def test_positional_resrefs_and_modules(self):
        command = diagnostics.build_command("tis_diagnostic", ["AR0072", "--game", "BG2EE"])
        self.assertIn("AR0072", command)
        command = diagnostics.build_command("unit_tests", ["test_tlk_handler"], python="py")
        self.assertEqual(command[-1], "tools.tests.test_tlk_handler")

    def test_rejects_everything_not_whitelisted(self):
        bad = [
            ("rm", []),
            ("test_suite", ["--out", "x"]),
            ("tis_diagnostic", ["--csv", "x.csv"]),
            ("test_suite", ["--test", "9"]),
            ("test_suite", ["--schema", "ARE; rm -rf /"]),
            ("test_suite", ["--game"]),
            ("test_suite", ["stray"]),
            ("unit_tests", ["test_suite"]),
            ("tis_diagnostic", ["../../etc/passwd"]),
            ("test_suite", ["--threads", "-1"]),
        ]
        for tool, args in bad:
            with self.subTest(tool=tool, args=args):
                with self.assertRaises(diagnostics.DiagnosticError):
                    diagnostics.build_command(tool, args)

    def test_truncation_keeps_head_and_tail(self):
        text = "H" * 100 + "M" * 1000 + "T" * 100
        short = diagnostics.truncate_output(text, limit=200)
        self.assertIn("characters omitted", short)
        self.assertTrue(short.startswith("H"))
        self.assertTrue(short.endswith("T"))
        self.assertLess(len(short), 300)
        self.assertEqual(diagnostics.truncate_output("small", limit=200), "small")

    def test_run_reports_timeout_and_exit_code(self):
        result = diagnostics.run_diagnostic(str(REPO_ROOT), "unit_tests", ["test_tlk_handler"])
        self.assertIn("exit code 0", result)
        with mock.patch.dict(diagnostics.DIAGNOSTICS, {"slow": {
                "argv": ["-c", "import time; time.sleep(30)"], "always": [], "flags": {},
                "positional": None, "description": ""}}):
            result = diagnostics.run_diagnostic(str(REPO_ROOT), "slow", [], timeout_seconds=1)
        self.assertIn("TIMED OUT", result)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = tool_registry.build_registry("fake", str(REPO_ROOT))

    def call(self, name, **arguments):
        return self.registry.call(name, arguments)

    def test_read_bytes_window_and_cap(self):
        text = self.call("read_bytes", game="fake", resref="test01", restype="are",
                         offset=0, length=16)
        self.assertIn("bytes 0x0-0xf of 608", text)
        self.assertIn("|AREAV1.0", text)
        with self.assertRaisesRegex(ValueError, "capped at 256"):
            self.call("read_bytes", game="FAKE", resref="TEST01", restype="ARE", length=257)
        with self.assertRaisesRegex(ValueError, "past the end"):
            self.call("read_bytes", game="FAKE", resref="TEST01", restype="ARE", offset=10000)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            self.call("locate", game="FAKE", resref="../x", restype="ARE")
        with self.assertRaises(LookupError):
            self.call("locate", game="FAKE", resref="NOPE", restype="ARE")
        with self.assertRaises(LookupError):
            self.call("describe", game="OTHER", resref="TEST01", restype="ARE")

    def test_locate_and_describe_report_facts_only(self):
        located = json.loads(self.call("locate", game="FAKE", resref="TEST01", restype="ARE"))
        self.assertEqual(located["key_entry"]["size"], 608)
        described = json.loads(self.call("describe", game="FAKE", resref="TEST01", restype="ARE"))
        self.assertEqual(described["sections"]["header"]["entries"], 1)

    def test_tool_specs_are_complete(self):
        names = {spec["name"] for spec in self.registry.describe()}
        self.assertTrue({"list_games", "locate", "describe", "read_bytes",
                         "run_diagnostic"} <= names)
        for spec in self.registry.describe():
            self.assertEqual(spec["inputSchema"]["type"], "object")


class FingerprintTests(unittest.TestCase):
    def test_changes_with_sources_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            first = source_fingerprint(root)
            self.assertEqual(first, source_fingerprint(root))
            (root / "notes.txt").write_text("ignored")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "a.py").write_text("ignored")
            self.assertEqual(first, source_fingerprint(root))
            (root / "a.py").write_text("x = 22\n")
            self.assertNotEqual(first, source_fingerprint(root))
            (root / "b.yaml").write_text("k: v\n")
            self.assertNotEqual(source_fingerprint(root), first)

    def test_excluded_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "shim.py").write_text("a")
            before = source_fingerprint(root, exclude=[root / "shim.py"])
            (root / "shim.py").write_text("changed")
            self.assertEqual(before, source_fingerprint(root, exclude=[root / "shim.py"]))


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.watch = self.tmp / "src"
        self.watch.mkdir()
        (self.watch / "module.py").write_text("VALUE = 1\n")
        self.changes = []
        self.supervisor = self.make_supervisor()
        self.addCleanup(self.supervisor.stop)
        self.addCleanup(self._tmp.cleanup)

    def make_supervisor(self, backend="fake"):
        return Supervisor(REPO_ROOT, backend=backend, watch_root=self.watch,
                          log_path=self.tmp / "worker.log",
                          on_tools_changed=lambda: self.changes.append(1))

    def pid(self):
        return int(self.supervisor.call("debug_pid", {}))

    def edit_source(self, text):
        (self.watch / "module.py").write_text(text)

    def test_worker_is_reused_until_sources_change(self):
        first = self.pid()
        self.assertEqual(first, self.pid())
        self.edit_source("VALUE = 2222\n")
        second = self.pid()
        self.assertNotEqual(first, second)
        self.assertEqual(self.supervisor.status()["worker"]["restarts"], 1)

    def test_reload_replaces_worker(self):
        first = self.pid()
        self.supervisor.reload()
        self.assertNotEqual(first, self.pid())

    def test_crash_is_reported_then_recovered(self):
        first = self.pid()
        with self.assertRaisesRegex(WorkerError, "exited during the call"):
            self.supervisor.call("debug_exit", {})
        self.assertNotEqual(first, self.pid())

    def test_timeout_kills_worker_and_recovers(self):
        first = self.pid()
        with self.assertRaisesRegex(WorkerError, "timed out"):
            self.supervisor.call("debug_sleep", {"seconds": 30})
        self.assertNotEqual(first, self.pid())

    def test_broken_worker_reports_log_and_does_not_loop(self):
        broken = self.make_supervisor(backend="nonexistent")
        self.addCleanup(broken.stop)
        for _ in range(2):
            with self.assertRaisesRegex(WorkerError, "exited before it was ready"):
                broken.call("status", {})
        self.assertEqual(broken.start_attempts, 1)
        self.assertIn("invalid choice", broken.status()["last_error"])
        (self.watch / "module.py").write_text("VALUE = 333333\n")
        with self.assertRaises(WorkerError):
            broken.call("status", {})
        self.assertEqual(broken.start_attempts, 2)

    def test_unknown_tool_lists_known_ones(self):
        with self.assertRaisesRegex(WorkerError, "Known tools: .*read_bytes"):
            self.supervisor.call("nope", {})

    def test_tool_list_change_triggers_callback(self):
        flag = self.tmp / "flag"
        with mock.patch.dict(os.environ, {"PF_MCP_FAKE_FLAG": str(flag)}):
            self.pid()
            self.assertEqual(self.changes, [])
            flag.write_text("on")
            self.edit_source("VALUE = 44444\n")
            self.assertIn("fake_extra", {t["name"] for t in self.supervisor.tools()})
            self.assertEqual(self.changes, [1])


class ProtocolTests(unittest.TestCase):
    """Speaks JSON-RPC to the real shim process over stdio."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.watch = self.tmp / "src"
        self.watch.mkdir()
        (self.watch / "module.py").write_text("VALUE = 1\n")
        self.flag = self.tmp / "flag"
        env = dict(os.environ, PF_MCP_FAKE_FLAG=str(self.flag))
        self.proc = subprocess.Popen(
            [sys.executable, str(SHIM), "--backend", "fake", "--repo", str(REPO_ROOT),
             "--watch-root", str(self.watch), "--log", str(self.tmp / "worker.log")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env)
        self.addCleanup(self._close)
        self._next = 0

    def _close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc.stdout.close()
        self.proc.stderr.close()

    def rpc(self, method, params=None):
        """Sends a request and returns (response, notifications seen before it)."""
        self._next += 1
        request = {"jsonrpc": "2.0", "id": self._next, "method": method}
        if params is not None:
            request["params"] = params
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        notifications = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                self.fail("shim closed its output: " + self.proc.stderr.read())
            message = json.loads(line)
            if message.get("id") == self._next:
                return message, notifications
            notifications.append(message)

    def tool(self, name, **arguments):
        response, notifications = self.rpc("tools/call", {"name": name, "arguments": arguments})
        return response["result"], notifications

    def test_handshake_and_tool_list(self):
        response, _ = self.rpc("initialize", {"protocolVersion": "2025-03-26",
                                              "capabilities": {}, "clientInfo": {"name": "t"}})
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-03-26")
        self.assertTrue(result["capabilities"]["tools"]["listChanged"])
        response, _ = self.rpc("tools/list")
        names = {t["name"] for t in response["result"]["tools"]}
        self.assertTrue({"status", "reload", "list_tools", "call", "read_bytes",
                         "run_diagnostic"} <= names)
        for tool in response["result"]["tools"]:
            self.assertNotIn("timeoutSeconds", tool)

    def test_calls_errors_and_unknown_method(self):
        result, _ = self.tool("read_bytes", game="FAKE", resref="TEST01", restype="ARE", length=8)
        self.assertFalse(result["isError"])
        self.assertIn("AREAV1.0", result["content"][0]["text"])
        result, _ = self.tool("read_bytes", game="FAKE", resref="TEST01", restype="ARE",
                              length=999)
        self.assertTrue(result["isError"])
        result, _ = self.tool("call", tool="read_bytes", arguments={
            "game": "FAKE", "resref": "TEST02", "restype": "ITM", "length": 4})
        self.assertIn("ITM", result["content"][0]["text"])
        response, _ = self.rpc("no/such/method")
        self.assertEqual(response["error"]["code"], -32601)
        response, _ = self.rpc("ping")
        self.assertEqual(response["result"], {})

    def test_reload_keeps_connection_and_announces_new_tools(self):
        first = int(self.tool("debug_pid")[0]["content"][0]["text"])
        self.flag.write_text("on")
        (self.watch / "module.py").write_text("VALUE = 5555555\n")
        result, notifications = self.tool("debug_pid")
        self.assertNotEqual(int(result["content"][0]["text"]), first)
        self.assertIn("notifications/tools/list_changed", [n.get("method") for n in notifications])
        response, _ = self.rpc("tools/list")
        self.assertIn("fake_extra", {t["name"] for t in response["result"]["tools"]})
        status = json.loads(self.tool("status")[0]["content"][0]["text"])
        self.assertEqual(status["worker"]["restarts"], 1)
        self.assertFalse(status["shim_stale"])


if __name__ == "__main__":
    unittest.main()
