"""Stable MCP shim: owns the client connection and supervises a disposable worker.

This file is deliberately small and imports only the standard library, never
anything from the rest of the repository. Claude Desktop starts it once and
keeps talking to it; the real work happens in ``worker.py``, a child process
that is restarted whenever the repository's sources change, on request, or
after a crash or timeout. Editing this file is the one change that still needs
a restart of the MCP connection (``status`` reports when that is the case).

It speaks the small subset of MCP that a tools-only server needs (JSON-RPC 2.0,
one message per line over stdio): ``initialize``, ``ping``, ``tools/list`` and
``tools/call``, plus the ``notifications/tools/list_changed`` notification.

See docs/MCP-Server.md for the design.

Usage:
    python tools/mcp_server/shim.py [--repo PATH] [--python EXE] [--backend NAME]
"""

import argparse
import hashlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SHIM_VERSION = "1"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "planarforge"

WATCHED_SUFFIXES = (".py", ".yaml", ".yml")
SKIPPED_DIRS = frozenset({
    ".git", "__pycache__", "logs", ".cache", ".venv", "venv", "node_modules", "docs",
})
START_TIMEOUT_SECONDS = 60
DEFAULT_CALL_TIMEOUT_SECONDS = 120
STDERR_TAIL_BYTES = 3000

FIXED_TOOLS = [
    {
        "name": "status",
        "description": "Report the shim and worker state: versions, worker pid and age, "
                       "source fingerprint, restart count and the last start error.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "reload",
        "description": "Restart the worker so it picks up code and schema changes. "
                       "Changed sources are also detected automatically before each call.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_tools",
        "description": "List the worker's tools with their input schemas. Use this with "
                       "'call' if the client's own tool list is out of date.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "call",
        "description": "Call any worker tool by name, e.g. tool='locate' with its arguments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "Worker tool name."},
                "arguments": {"type": "object", "description": "Arguments for that tool."},
            },
            "required": ["tool"],
        },
    },
]


class WorkerError(Exception):
    """Raised when the worker cannot be started, dies, times out or reports an error."""


def source_fingerprint(root, exclude=()):
    """Fingerprints the watched source files under a directory.

    Args:
        root: Directory to scan.
        exclude: Absolute paths of files to leave out (the shim itself).

    Returns:
        str: A hex digest that changes when a ``.py``/``.yaml`` file is added,
        removed, resized or modified.
    """
    digest = hashlib.sha1()
    root = os.fspath(root)
    excluded = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRS)
        for name in filenames:
            if not name.endswith(WATCHED_SUFFIXES):
                continue
            path = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(path)) in excluded:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((os.path.relpath(path, root), stat.st_size, stat.st_mtime_ns))
    for entry in sorted(entries):
        digest.update(repr(entry).encode("utf-8"))
    return digest.hexdigest()


def kill_process_tree(process):
    """Kills a process and everything it started, reaps it and closes its pipes.

    Safe to call on a process that has already exited.
    """
    if process.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=15, check=False)
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    for pipe in (process.stdin, process.stdout):
        try:
            if pipe is not None:
                pipe.close()
        except (OSError, ValueError):
            pass


class Supervisor:
    """Starts, watches, calls and restarts the worker process.

    Calls are serialised: the worker handles one request at a time.

    Args:
        repo: Repository root; the worker runs with this as its working directory.
        python: Interpreter used for the worker.
        backend: Backend name passed to the worker (``loader`` or ``fake``).
        watch_root: Directory fingerprinted for changes (defaults to ``repo``).
        log_path: File that receives the worker's stderr.
        on_tools_changed: Called (no arguments) when a restart changes the tool list.
    """

    def __init__(self, repo, python=None, backend="loader", watch_root=None,
                 log_path=None, on_tools_changed=None):
        self.repo = Path(repo).resolve()
        self.python = python or sys.executable
        self.backend = backend
        self.watch_root = Path(watch_root).resolve() if watch_root else self.repo
        self.log_path = Path(log_path) if log_path else self.repo / "logs" / "mcp-worker.log"
        self.on_tools_changed = on_tools_changed
        self._shim_path = Path(__file__).resolve()
        self._shim_mtime = self._shim_path.stat().st_mtime_ns
        self._lock = threading.RLock()
        self._process = None
        self._responses = None
        self._reader = None
        self._fingerprint = None
        self._started_at = None
        self._tools = []
        self._next_id = 0
        self.restarts = 0
        self.start_attempts = 0
        self.last_error = None
        self._failed_fingerprint = None

    # -- lifecycle ---------------------------------------------------------

    def _current_fingerprint(self):
        return source_fingerprint(self.watch_root, exclude=[self._shim_path])

    def _alive(self):
        return self._process is not None and self._process.poll() is None

    def stop(self):
        """Stops the worker if it is running."""
        with self._lock:
            if self._process is not None:
                kill_process_tree(self._process)
            self._process = None

    def _read_stdout(self, process, responses):
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                responses.put(json.loads(line))
            except ValueError:
                continue
        responses.put(None)  # EOF: the worker is gone

    def _log_size(self):
        try:
            return self.log_path.stat().st_size
        except OSError:
            return 0

    def _log_tail_since(self, offset):
        try:
            with open(self.log_path, "rb") as handle:
                handle.seek(offset)
                data = handle.read()
        except OSError:
            return ""
        return data[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace").strip()

    def _spawn(self, fingerprint):
        """Starts a fresh worker and waits for its ready message."""
        self.stop()
        self.start_attempts += 1
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_offset = self._log_size()
        log_handle = open(self.log_path, "ab")
        worker = Path(__file__).with_name("worker.py")
        argv = [self.python, "-u", str(worker), "--repo", str(self.repo),
                "--backend", self.backend]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            argv, cwd=str(self.repo), env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=log_handle, text=True,
            encoding="utf-8", bufsize=1, **kwargs)
        log_handle.close()
        responses = queue.Queue()
        reader = threading.Thread(target=self._read_stdout, args=(process, responses),
                                  daemon=True)
        reader.start()
        self._process, self._responses, self._reader = process, responses, reader
        try:
            ready = responses.get(timeout=START_TIMEOUT_SECONDS)
        except queue.Empty:
            ready = None
            reason = "did not become ready within %d s" % START_TIMEOUT_SECONDS
        else:
            reason = "exited before it was ready"
        if not ready or not ready.get("ready"):
            kill_process_tree(process)
            self._process = None
            tail = self._log_tail_since(log_offset)
            self._failed_fingerprint = fingerprint
            self.last_error = "Worker %s.%s" % (reason, ("\n" + tail) if tail else "")
            raise WorkerError(self.last_error)
        self._failed_fingerprint = None
        self.last_error = None
        self._fingerprint = fingerprint
        self._started_at = time.time()
        old_tools = self._tools
        self._tools = self._request({"op": "list_tools"}, 30)
        if self.restarts and old_tools != self._tools and self.on_tools_changed:
            self.on_tools_changed()
        self.restarts += 1

    def _ensure_worker(self):
        fingerprint = self._current_fingerprint()
        if self._alive() and fingerprint == self._fingerprint:
            return
        if not self._alive() and fingerprint == self._failed_fingerprint and self.last_error:
            raise WorkerError(self.last_error + "\n(Fix the sources, or call 'reload'.)")
        self._spawn(fingerprint)

    def reload(self):
        """Restarts the worker regardless of whether sources changed."""
        with self._lock:
            self._failed_fingerprint = None
            self._spawn(self._current_fingerprint())

    # -- requests ----------------------------------------------------------

    def _request(self, message, timeout):
        """Sends one request to the worker and waits for the matching response."""
        self._next_id += 1
        request_id = self._next_id
        message = dict(message, id=request_id)
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError):
            kill_process_tree(self._process)
            self._process = None
            raise WorkerError("The worker is not running; it will be restarted on the next call.")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            try:
                response = self._responses.get(timeout=max(remaining, 0.01))
            except queue.Empty:
                kill_process_tree(self._process)
                self._process = None
                raise WorkerError("The call timed out after %s s; the worker was stopped and "
                                  "will be restarted on the next call." % timeout)
            if response is None:
                kill_process_tree(self._process)  # reaps the exited worker, closes pipes
                self._process = None
                raise WorkerError("The worker exited during the call; it will be restarted on "
                                  "the next call. See logs/mcp-worker.log.")
            if response.get("id") != request_id:
                continue  # stale answer from an earlier, abandoned call
            if not response.get("ok"):
                raise WorkerError(str(response.get("error", "unknown worker error")))
            return response.get("result")

    def tools(self):
        """Returns the worker's tool list, starting the worker if needed."""
        with self._lock:
            self._ensure_worker()
            return list(self._tools)

    def call(self, tool, arguments):
        """Calls a worker tool.

        Args:
            tool: Worker tool name.
            arguments: Argument dict.

        Returns:
            str: The tool's text result.

        Raises:
            WorkerError: If the worker fails, times out or rejects the call.
        """
        with self._lock:
            self._ensure_worker()
            spec = next((t for t in self._tools if t["name"] == tool), None)
            if spec is None:
                raise WorkerError("Unknown worker tool '%s'. Known tools: %s"
                                  % (tool, ", ".join(t["name"] for t in self._tools)))
            timeout = spec.get("timeoutSeconds", DEFAULT_CALL_TIMEOUT_SECONDS)
            return self._request({"op": "call", "tool": tool, "arguments": arguments or {}},
                                 timeout)

    def status(self):
        """Returns a JSON-serialisable description of shim and worker state."""
        with self._lock:
            try:
                shim_stale = self._shim_path.stat().st_mtime_ns != self._shim_mtime
            except OSError:
                shim_stale = False
            alive = self._alive()
            return {
                "shim_version": SHIM_VERSION,
                "shim_stale": shim_stale,
                "shim_stale_note": ("shim.py changed on disk; restart the MCP connection to "
                                    "use the new version") if shim_stale else None,
                "repo": str(self.repo),
                "python": self.python,
                "backend": self.backend,
                "worker": {
                    "running": alive,
                    "pid": self._process.pid if alive else None,
                    "age_seconds": round(time.time() - self._started_at, 1)
                    if alive and self._started_at else None,
                    "fingerprint": (self._fingerprint or "")[:12] or None,
                    "restarts": max(self.restarts - 1, 0),
                    "start_attempts": self.start_attempts,
                    "tool_count": len(self._tools),
                },
                "last_error": self.last_error,
            }


class McpServer:
    """Minimal MCP server over stdio (newline-delimited JSON-RPC 2.0).

    Args:
        supervisor: The worker supervisor.
        stdin: Text stream to read requests from.
        stdout: Text stream to write responses to.
    """

    def __init__(self, supervisor, stdin=None, stdout=None):
        self.supervisor = supervisor
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self._write_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=8)
        supervisor.on_tools_changed = self._notify_tools_changed

    def _send(self, message):
        with self._write_lock:
            self.stdout.write(json.dumps(message) + "\n")
            self.stdout.flush()

    def _notify_tools_changed(self):
        self._send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})

    def serve(self):
        """Reads requests until stdin closes."""
        for line in self.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": "Parse error"}})
                continue
            self._pool.submit(self._handle, message)
        self._pool.shutdown(wait=False)
        self.supervisor.stop()

    def _handle(self, message):
        method = message.get("method")
        request_id = message.get("id")
        if request_id is None:
            return  # notifications (initialized, cancelled, ...) need no answer
        try:
            result = self._dispatch(method, message.get("params") or {})
        except KeyError:
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32601, "message": "Method not found: %s" % method}})
            return
        except Exception as exc:  # protocol-level failure, not a tool error
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32603, "message": "Internal error: %s" % exc}})
            return
        self._send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _dispatch(self, method, params):
        if method == "initialize":
            return {
                "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": SERVER_NAME, "version": SHIM_VERSION},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._tool_list()}
        if method == "tools/call":
            return self._call_tool(params.get("name"), params.get("arguments") or {})
        raise KeyError(method)

    def _tool_list(self):
        tools = list(FIXED_TOOLS)
        try:
            for spec in self.supervisor.tools():
                tools.append({k: v for k, v in spec.items() if k != "timeoutSeconds"})
        except WorkerError:
            pass  # fixed tools stay available so 'status' can explain the failure
        return tools

    def _call_tool(self, name, arguments):
        try:
            if name == "status":
                text = json.dumps(self.supervisor.status(), indent=2)
            elif name == "reload":
                self.supervisor.reload()
                text = json.dumps(self.supervisor.status(), indent=2)
            elif name == "list_tools":
                text = json.dumps(self.supervisor.tools(), indent=2)
            elif name == "call":
                text = self.supervisor.call(arguments.get("tool"), arguments.get("arguments"))
            else:
                text = self.supervisor.call(name, arguments)
        except WorkerError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        return {"content": [{"type": "text", "text": text}], "isError": False}


def main(argv=None):
    """Runs the shim until the client closes stdin."""
    default_repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="PlanarForge MCP shim")
    parser.add_argument("--repo", default=str(default_repo), help="repository root")
    parser.add_argument("--python", default=None, help="interpreter for the worker")
    parser.add_argument("--backend", default="loader", choices=["loader", "fake"],
                        help="'fake' serves synthetic data (for tests)")
    parser.add_argument("--watch-root", default=None, help="directory to fingerprint (tests)")
    parser.add_argument("--log", default=None, help="worker log file (default logs/mcp-worker.log)")
    args = parser.parse_args(argv)
    supervisor = Supervisor(args.repo, python=args.python, backend=args.backend,
                            watch_root=args.watch_root, log_path=args.log)
    McpServer(supervisor).serve()


if __name__ == "__main__":
    main()
