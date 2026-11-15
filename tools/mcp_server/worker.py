"""MCP worker: runs the real tools and talks to the shim over pipes.

The shim starts this file as a child process and sends it one JSON object per
line on stdin; it answers with one JSON object per line on stdout. Everything
else the process (or the libraries it imports) prints is redirected to stderr,
which the shim writes to ``logs/mcp-worker.log``, so stray ``print`` calls can
never corrupt the protocol.

Requests:
    {"id": 1, "op": "list_tools"}
    {"id": 2, "op": "call", "tool": "locate", "arguments": {...}}

Responses:
    {"id": 1, "ok": true, "result": ...}
    {"id": 2, "ok": false, "error": "message"}

Usage (started by the shim):
    python worker.py --repo PATH --backend loader|fake
"""

import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    """Serves requests from stdin until it closes."""
    parser = argparse.ArgumentParser(description="PlanarForge MCP worker")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--backend", default="loader", choices=["loader", "fake"])
    args = parser.parse_args(argv)

    protocol_out = sys.stdout
    sys.stdout = sys.stderr  # keep stray prints out of the protocol stream

    # Running this file as a script puts its own directory first on sys.path, where
    # sibling modules would shadow top-level names; drop it and use the repo root.
    script_dir = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if str(Path(p or ".").resolve()) != script_dir]
    repo = str(Path(args.repo).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)

    from tools.mcp_server import tool_registry as tool_module  # imported after sys.path is set

    registry = tool_module.build_registry(args.backend, repo)

    def reply(payload):
        protocol_out.write(json.dumps(payload) + "\n")
        protocol_out.flush()

    reply({"ready": True, "backend": args.backend})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            request_id = request.get("id")
            if request.get("op") == "list_tools":
                result = registry.describe()
            elif request.get("op") == "call":
                result = registry.call(request.get("tool"), request.get("arguments") or {})
            else:
                raise ValueError("unknown op %r" % request.get("op"))
            reply({"id": request_id, "ok": True, "result": result})
        except Exception as exc:  # report every failure to the shim; never die silently
            request_id = locals().get("request_id")
            reply({"id": request_id, "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})


if __name__ == "__main__":
    main()
