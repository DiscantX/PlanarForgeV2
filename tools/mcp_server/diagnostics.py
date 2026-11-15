"""Whitelisted diagnostic runs for the MCP ``run_diagnostic`` tool.

Only the tools named in ``DIAGNOSTICS`` can be run, only with the flags listed
for them, and never through a shell. Flags that write files (``--out``,
``--csv``) are not allowed. Output is capped so a verbose run cannot flood the
conversation.
"""

import os
import re
import signal
import subprocess
import sys
import time

DEFAULT_TIMEOUT_SECONDS = 600
MAX_TIMEOUT_SECONDS = 1800
MAX_OUTPUT_CHARS = 60000

_WORD = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")
_CSV = re.compile(r"^[A-Za-z0-9_,.\-]{1,80}$")

# Game-free unit test modules that may be run by name.
UNIT_TEST_MODULES = (
    "test_tis_decoder", "test_table_resolver", "test_tlk_handler", "test_pvrz_decoder",
    "test_pvrz_scan", "test_biff_handler", "test_installation_finder",
    "test_tis_diagnostic", "test_resource_serialization",
)

# Flag specs: None = no value, "int" = integer, "word"/"csv" = restricted text,
# a tuple = one of the listed values.
DIAGNOSTICS = {
    "test_suite": {
        "argv": ["tools/tests/test_suite.py"],
        "always": ["--no-progress"],
        "flags": {
            "--test": ("1", "2", "3", "4"),
            "--schema": "word", "--resref": "word", "--game": "csv",
            "--audit-gaps": None,
            "--gap-detail-level": ("summary", "nonzero", "full"),
            "--threads": "int",
        },
        "positional": None,
        "description": "Round-trip fidelity suite (tests 1 to 4). Needs installed games for 1 to 3.",
    },
    "tis_diagnostic": {
        "argv": ["tools/tis_diagnostic.py"],
        "always": [],
        "flags": {
            "--scan": None, "--no-wed": None, "--limit": "int", "--game": "word",
            "--overlay": "int", "--cells": "int", "--no-pages": None, "--no-bif": None,
            "--no-viewer": None,
        },
        "positional": "word",
        "description": "TIS/WED diagnostic for resrefs (positional) or a whole game (--scan).",
    },
    "pvrz_scan": {
        "argv": ["tools/pvrz_scan.py"],
        "always": [],
        "flags": {"--game": "word", "--limit": "int"},
        "positional": None,
        "description": "Scan every PVRZ page of a game against the documented layout.",
    },
    "unit_tests": {
        "argv": ["-m", "unittest"],
        "always": [],
        "flags": {},
        "positional": "module",
        "description": "Game-free unit test modules, named without the package prefix.",
    },
}


class DiagnosticError(ValueError):
    """Raised when a requested diagnostic is not allowed."""


def _check_value(spec, value, flag):
    if isinstance(spec, tuple):
        if value not in spec:
            raise DiagnosticError("%s must be one of %s" % (flag, ", ".join(spec)))
    elif spec == "int":
        if not re.fullmatch(r"\d{1,6}", value):
            raise DiagnosticError("%s needs a whole number" % flag)
    elif spec == "word":
        if not _WORD.match(value):
            raise DiagnosticError("%s has an invalid value" % flag)
    elif spec == "csv":
        if not _CSV.match(value):
            raise DiagnosticError("%s has an invalid value" % flag)


def build_command(tool, args, python=None):
    """Validates a request and builds the argument vector to run.

    Args:
        tool: Name of a whitelisted diagnostic.
        args: List of argument strings for it.
        python: Interpreter to use (defaults to the current one).

    Returns:
        list[str]: The argv to execute, relative to the repository root.

    Raises:
        DiagnosticError: If the tool or any argument is not allowed.
    """
    entry = DIAGNOSTICS.get(tool)
    if entry is None:
        raise DiagnosticError("Unknown diagnostic '%s'. Allowed: %s"
                              % (tool, ", ".join(sorted(DIAGNOSTICS))))
    args = list(args or [])
    if not all(isinstance(a, str) for a in args):
        raise DiagnosticError("Arguments must be strings")
    command = [python or sys.executable] + list(entry["argv"]) + list(entry["always"])
    modules = []
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("-"):
            if token not in entry["flags"]:
                raise DiagnosticError("Flag '%s' is not allowed for %s. Allowed: %s"
                                      % (token, tool, ", ".join(entry["flags"]) or "none"))
            spec = entry["flags"][token]
            command.append(token)
            if spec is not None:
                index += 1
                if index >= len(args):
                    raise DiagnosticError("%s needs a value" % token)
                _check_value(spec, args[index], token)
                command.append(args[index])
        else:
            kind = entry["positional"]
            if kind is None:
                raise DiagnosticError("%s takes no positional arguments" % tool)
            if kind == "module":
                if token not in UNIT_TEST_MODULES:
                    raise DiagnosticError("Unknown test module '%s'. Allowed: %s"
                                          % (token, ", ".join(UNIT_TEST_MODULES)))
                modules.append("tools.tests." + token)
            else:
                _check_value(kind, token, "argument")
                command.append(token)
        index += 1
    if tool == "unit_tests":
        command += modules or ["tools.tests." + m for m in UNIT_TEST_MODULES]
    return command


def truncate_output(text, limit=MAX_OUTPUT_CHARS):
    """Shortens long output, keeping the start and (more of) the end.

    Summaries are usually printed last, so the tail is kept in preference.
    """
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    omitted = len(text) - limit
    return "%s\n\n[... %d characters omitted ...]\n\n%s" % (text[:head], omitted, text[-tail:])


def run_diagnostic(repo, tool, args, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, python=None):
    """Runs a whitelisted diagnostic and returns its (capped) output.

    Args:
        repo: Repository root, used as the working directory.
        tool: Whitelisted diagnostic name.
        args: Argument strings for it.
        timeout_seconds: Kill the run after this long (capped at 30 minutes).
        python: Interpreter to use.

    Returns:
        str: A one-line summary followed by the combined stdout and stderr.

    Raises:
        DiagnosticError: If the request is not allowed.
    """
    command = build_command(tool, args, python=python)
    timeout = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", **kwargs)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process)
        output, _ = process.communicate()
    elapsed = time.monotonic() - started
    if timed_out:
        summary = "TIMED OUT after %d s (killed); output so far:" % timeout
    else:
        summary = "exit code %d in %.1f s" % (process.returncode, elapsed)
    return "%s: %s\n%s" % (tool, summary, truncate_output(output or ""))


def _kill_tree(process):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=15, check=False)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        process.kill()
