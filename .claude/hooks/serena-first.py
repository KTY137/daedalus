#!/usr/bin/env python3
"""PreToolUse hook: route symbol work through Serena instead of Grep/Read.

Why this exists
---------------
Serena exposes 21 LSP-backed tools (find_symbol, get_symbols_overview,
find_referencing_symbols, ...). Grepping for `def foo` and reading whole
source files is strictly worse: it costs more tokens, misses call sites that
do not match the pattern, and returns no structure. The failure mode is not
ignorance but drift -- the cheap habit wins whenever nothing stops it.

So this stops it mechanically rather than by instruction.

Fail-open by construction
-------------------------
The hook denies ONLY when Serena is actually reachable. If Serena is down,
misconfigured, or the dashboard is disabled, every call passes through
untouched. A guard whose failure mode is "no symbol lookup is possible at
all" would be worse than the drift it prevents -- cf. amendment proposal 002
point B, which names an unrecoverable guard state as a defect, not a
protection.

Escape hatches, in order of bluntness:
  * targeted reads (offset/limit) always pass;
  * files under the line threshold always pass;
  * a Read passes once a Serena tool has touched that file this session;
  * DAEDALUS_SERENA_HOOK=off disables the hook entirely.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from pathlib import Path

# Serena's web dashboard. Presence of a listener is the cheapest reliable
# proof that a Serena process is live for this project; the MCP transport
# itself is not observable from a hook.
SERENA_HOST = "127.0.0.1"
SERENA_PORT = int(os.environ.get("SERENA_DASHBOARD_PORT", "24282"))
PROBE_TIMEOUT_S = 0.15

# Below this, reading the whole file is cheaper than an overview round-trip.
WHOLE_FILE_LINE_THRESHOLD = 120

SOURCE_SUFFIXES = frozenset(
    {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs"}
)

# A pattern naming a definition keyword is a symbol lookup wearing a regex.
# Kept to keywords that introduce a declaration -- deliberately not `type`
# or `impl`, which collide with ordinary prose too often.
DEFINITION_PATTERN = re.compile(
    r"(?:^|[^0-9A-Za-z_])(def|class|function|interface|struct|enum|fn|trait)\b",
    re.IGNORECASE,
)

# Serena tool names as they appear in the transcript.
SERENA_TOOL = re.compile(r"mcp__serena__(\w+)")

# Only the last slice of the transcript is scanned; it is append-only and can
# grow to hundreds of megabytes over a long session.
TRANSCRIPT_TAIL_BYTES = 2_000_000


def serena_is_reachable() -> bool:
    """True when something is listening on Serena's dashboard port."""
    try:
        with socket.create_connection(
            (SERENA_HOST, SERENA_PORT), timeout=PROBE_TIMEOUT_S
        ):
            return True
    except OSError:
        return False


def transcript_mentions(transcript_path: str, needle: str) -> bool:
    """True when a Serena tool call in this session referenced `needle`."""
    if not transcript_path:
        return False
    try:
        path = Path(transcript_path)
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > TRANSCRIPT_TAIL_BYTES:
                handle.seek(size - TRANSCRIPT_TAIL_BYTES)
            blob = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return False

    needle = needle.lower()
    for line in blob.splitlines():
        if "mcp__serena__" in line and needle in line.lower():
            return True
    return False


def line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")


def check_grep(tool_input: dict) -> str | None:
    pattern = tool_input.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        return None
    match = DEFINITION_PATTERN.search(pattern)
    if match is None:
        return None
    return (
        f"Serena is running and this Grep ({pattern!r}) is a symbol lookup: "
        f"the pattern names the declaration keyword {match.group(1)!r}.\n"
        "Use mcp__serena__find_symbol (name_path, optionally "
        "relative_path) instead -- it resolves through the language server, "
        "so it returns the definition with its body and location and does not "
        "miss declarations the regex fails to match. For call sites use "
        "mcp__serena__find_referencing_symbols.\n"
        "If you genuinely want a text search, drop the declaration keyword "
        "from the pattern."
    )


def check_read(tool_input: dict, transcript_path: str) -> str | None:
    raw_path = tool_input.get("file_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None

    # A targeted read is the intended end state, not the drift.
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return None

    path = Path(raw_path)
    if path.suffix.lower() not in SOURCE_SUFFIXES:
        return None

    lines = line_count(path)
    if lines <= WHOLE_FILE_LINE_THRESHOLD:
        return None

    # Overview first, then read: once Serena has described this file, a full
    # read is an informed decision rather than a reflex.
    if transcript_mentions(transcript_path, path.name):
        return None

    return (
        f"Serena is running and {path.name} is {lines} lines. Reading it whole "
        "spends the tokens before knowing which part matters.\n"
        f"Call mcp__serena__get_symbols_overview (relative_path={path.name!r}) "
        "first, then mcp__serena__find_symbol with include_body=true for the "
        "symbol you actually need.\n"
        "After any Serena tool has touched this file, a full Read is allowed. "
        "A targeted Read (offset/limit) is always allowed."
    )


def main() -> int:
    if os.environ.get("DAEDALUS_SERENA_HOOK", "").lower() == "off":
        return 0

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, UnicodeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    if tool_name == "Grep":
        checker = check_grep(tool_input)
    elif tool_name == "Read":
        checker = check_read(tool_input, str(payload.get("transcript_path") or ""))
    else:
        return 0

    if checker is None:
        return 0

    # Probed last: it costs a socket call, and most invocations never get here.
    if not serena_is_reachable():
        return 0

    deny(checker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
