"""Tool definitions served by the MCP worker.

Each tool is a spec (name, description, JSON input schema, time limit) plus a
handler that takes an argument dict and returns text. Handlers raise on bad
input; the worker reports the message to the shim, which returns it to the
assistant as a tool error.
"""

import json
import os
import re
import time
from pathlib import Path

from tools.mcp_server import diagnostics
from tools.mcp_server.backend import FakeBackend, LoaderBackend

MAX_READ_BYTES = 256
DEFAULT_READ_BYTES = 64
_RESREF = re.compile(r"^[A-Za-z0-9_#\-]{1,16}$")
_RESTYPE = re.compile(r"^[A-Za-z0-9_]{2,8}$")
_GAME = re.compile(r"^[A-Za-z0-9_]{1,12}$")


class ToolRegistry:
    """Holds tool specs and handlers."""

    def __init__(self):
        self._specs = {}
        self._handlers = {}

    def register(self, name, description, properties, required, handler, timeout=120):
        """Adds a tool.

        Args:
            name: Tool name.
            description: What the tool does, for the assistant.
            properties: JSON-schema ``properties`` for the arguments.
            required: Names of required arguments.
            handler: Callable taking the argument dict and returning text.
            timeout: Seconds the shim waits before killing the worker.
        """
        self._specs[name] = {
            "name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required},
            "timeoutSeconds": timeout,
        }
        self._handlers[name] = handler

    def describe(self):
        """Returns the list of tool specs."""
        return list(self._specs.values())

    def call(self, name, arguments):
        """Runs a tool and returns its text result."""
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError("unknown tool %r" % name)
        return handler(arguments)


def _text(arguments, key, pattern, label):
    value = arguments.get(key)
    if not isinstance(value, str) or not pattern.match(value):
        raise ValueError("'%s' must be a %s" % (key, label))
    return value


def _target(arguments):
    game = _text(arguments, "game", _GAME, "game id such as BG2EE").upper()
    resref = _text(arguments, "resref", _RESREF, "resource name of up to 8 characters")
    restype = _text(arguments, "restype", _RESTYPE, "resource type such as ARE").upper()
    return game, resref, restype


def hex_dump(data, base_offset=0):
    """Formats bytes as offset, hex and ASCII columns, 16 bytes per line."""
    lines = []
    for start in range(0, len(data), 16):
        chunk = data[start:start + 16]
        hexes = " ".join("%02x" % b for b in chunk).ljust(47)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append("%08x  %s  |%s|" % (base_offset + start, hexes, text))
    return "\n".join(lines)


def build_registry(backend_name, repo):
    """Creates the registry of tools for a backend.

    Args:
        backend_name: ``"loader"`` for installed games, ``"fake"`` for tests.
        repo: Repository root (working directory for diagnostics).

    Returns:
        ToolRegistry: The populated registry.
    """
    backend = FakeBackend() if backend_name == "fake" else LoaderBackend()
    registry = ToolRegistry()
    target_props = {
        "game": {"type": "string", "description": "Game id, e.g. BG2EE, IWDEE, PSTEE."},
        "resref": {"type": "string", "description": "Resource name, e.g. AR0072."},
        "restype": {"type": "string", "description": "Resource type, e.g. ARE, WED, TIS."},
    }
    target_required = ["game", "resref", "restype"]

    def list_games(_arguments):
        return json.dumps(backend.list_games(), indent=2)

    def locate(arguments):
        return json.dumps(backend.locate(*_target(arguments)), indent=2)

    def describe(arguments):
        return json.dumps(backend.describe(*_target(arguments)), indent=2)

    def read_bytes(arguments):
        game, resref, restype = _target(arguments)
        offset = arguments.get("offset", 0)
        length = arguments.get("length", DEFAULT_READ_BYTES)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("'offset' must be a non-negative integer")
        if not isinstance(length, int) or length < 1:
            raise ValueError("'length' must be a positive integer")
        if length > MAX_READ_BYTES:
            raise ValueError("'length' is capped at %d bytes per call (game data policy); "
                             "ask for several windows if you need more" % MAX_READ_BYTES)
        data = backend.read_raw(game, resref, restype)
        window = data[offset:offset + length]
        if not window:
            raise ValueError("offset %d is past the end of the resource (%d bytes)"
                             % (offset, len(data)))
        header = "%s %s.%s: bytes 0x%x-0x%x of %d (0x%x)" % (
            game, resref.upper(), restype, offset, offset + len(window) - 1, len(data), len(data))
        return header + "\n" + hex_dump(window, offset)

    def run_diagnostic(arguments):
        tool = arguments.get("tool")
        args = arguments.get("args") or []
        timeout = arguments.get("timeout_seconds", diagnostics.DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(args, list):
            raise ValueError("'args' must be a list of strings")
        if not isinstance(timeout, int):
            raise ValueError("'timeout_seconds' must be an integer")
        return diagnostics.run_diagnostic(repo, tool, args, timeout_seconds=timeout)

    registry.register("list_games", "List the installed games the tool can read.", {}, [],
                      list_games)
    registry.register("locate", "Where a resource lives: override file and/or the KEY/BIF "
                      "entry, with sizes and locator indices.", target_props, target_required,
                      locate)
    registry.register("describe", "Structure of a parsed resource: schema, section entry "
                      "counts and field names, and scalar header values (no text or raw data).",
                      target_props, target_required, describe)
    registry.register(
        "read_bytes",
        "Hex dump of a window of a resource's raw bytes. At most %d bytes per call." % MAX_READ_BYTES,
        dict(target_props, offset={"type": "integer", "minimum": 0},
             length={"type": "integer", "minimum": 1, "maximum": MAX_READ_BYTES}),
        target_required, read_bytes)
    allowed = "; ".join("%s: %s" % (k, v["description"])
                        for k, v in sorted(diagnostics.DIAGNOSTICS.items()))
    registry.register(
        "run_diagnostic",
        "Run a whitelisted repository tool and return its output (capped). " + allowed,
        {"tool": {"type": "string", "enum": sorted(diagnostics.DIAGNOSTICS)},
         "args": {"type": "array", "items": {"type": "string"},
                  "description": "Flags and values, e.g. ['--test','2','--schema','ARE']."},
         "timeout_seconds": {"type": "integer", "minimum": 1,
                             "maximum": diagnostics.MAX_TIMEOUT_SECONDS}},
        ["tool"], run_diagnostic, timeout=diagnostics.MAX_TIMEOUT_SECONDS + 60)

    if backend_name == "fake":
        _register_test_tools(registry)
    return registry


def _register_test_tools(registry):
    """Tools that exist only with the fake backend, to exercise the shim."""

    def debug_pid(_arguments):
        return str(os.getpid())

    def debug_exit(_arguments):
        os._exit(3)

    def debug_sleep(arguments):
        time.sleep(float(arguments.get("seconds", 10)))
        return "slept"

    registry.register("debug_pid", "Test only: the worker's process id.", {}, [], debug_pid,
                      timeout=10)
    registry.register("debug_exit", "Test only: kill the worker.", {}, [], debug_exit, timeout=10)
    registry.register("debug_sleep", "Test only: sleep.", {"seconds": {"type": "number"}}, [],
                      debug_sleep, timeout=2)
    flag = os.environ.get("PF_MCP_FAKE_FLAG")
    if flag and Path(flag).exists():
        registry.register("fake_extra", "Test only: appears when the flag file exists.", {}, [],
                          lambda _a: "extra", timeout=10)
