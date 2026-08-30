# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tool-event handlers: PreToolUse (Serena routing, Serena wrong-tree write
guard) and PostToolUse (test-run fingerprint, docs-drift reminder).

Serena routing — three modes, ``DAEDALUS_SERENA_HOOK``
------------------------------------------------------
``advise`` (default): a Grep that is a symbol lookup wearing a regex, or a
whole-file Read of a large source file Serena has not described yet, goes
through UNCHANGED and a one-line Serena nudge rides along as
``additionalContext`` — once per file/pattern per session, so it cannot become
wallpaper. ``deny``: the amendment-003 behaviour (2026-08-21): the call is
refused with the same text as the reason. ``off``: no routing nudge at all.
The wrong-tree WRITE guard below is independent of the mode and stays on.

Why ``advise`` is the default: the owner's ``AGENTS.md`` of 2026-08-22 names
"a guard that blocks reading or measuring" a release-blocking defect, and the
same day's kit carried the deny hook across. Of two owner artefacts that
disagree, the design follows the explicit newer rule and leaves the switch.

Fail-open by construction, as before: the nudge/deny only fires when Serena's
dashboard port answers; targeted reads (offset/limit), small files, and files a
Serena tool already touched this session always pass.

The wrong-tree write guard is a real deny and has no advisory mode: it blocks
WRITING into another tree, never reading.
"""
from __future__ import annotations

import os
import re
import socket
import time
from pathlib import Path

from ._common import HookResult, sha256_text, update_state
from ._tree import SERENA_WRITE_TOOLS, serena_root_mismatch, source_fingerprint

SERENA_HOST = "127.0.0.1"
PROBE_TIMEOUT_S = 0.15
WHOLE_FILE_LINE_THRESHOLD = 120
SOURCE_SUFFIXES = frozenset({".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs"})
DEFINITION_PATTERN = re.compile(
    r"(?:^|[^0-9A-Za-z_])(def|class|function|interface|struct|enum|fn|trait)\b",
    re.IGNORECASE,
)
TRANSCRIPT_TAIL_BYTES = 2_000_000
SERENA_CALL = re.compile(r'"name"\s*:\s*"mcp__serena__\w+"')
ADVISED_CAP = 200
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

#: Commands that count as a test run. The head of the command (after an
#: optional ``cd … &&`` / ``;`` and optional ``uv run``) must be one of these
#: forms; ``echo pytest`` or ``grep pytest`` is not a test run.
#: Quoted or bare path after ``cd``, then ``&&`` or ``;``.
_CD_PREFIX = r'(?:cd\s+(?:"[^"]*"|' + chr(39) + '[^' + chr(39) + ']*' + chr(39) + r'|\S+)\s*(?:&&|;)\s*)?'
_UV_RUN_PREFIX = r"(?:uv(?:\.exe)?\s+run\s+)?"
TEST_COMMAND = re.compile(
    r"^\s*" + _CD_PREFIX
    + _UV_RUN_PREFIX
    + r"(?:(?:python(?:3)?|py)(?:\.exe)?\s+(?:-u\s+)?-m\s+(?:pytest|unittest)\b|pytest\b|py\.test\b)",
    re.IGNORECASE,
)
COMMIT_COMMAND = re.compile(r"(?:^|&&|;|\|)\s*git\s+commit\b")

DOCS_DRIFT_REMINDER = (
    "A commit just landed. If it changed structure, interfaces, or any number that "
    "appears in docs, dispatch the mnemosyne delegate now to bring HANDOFF/docs/status "
    "back in sync and stamp provenance (MEASURED / INHERITED / ASSUMED). If the commit "
    "was cosmetic (formatting, comments, test-only churn), skip it and say so in one clause."
)


def serena_mode(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    mode = (env.get("DAEDALUS_SERENA_HOOK") or "advise").strip().lower()
    return mode if mode in {"advise", "deny", "off"} else "advise"


def serena_is_reachable(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    try:
        port = int(env.get("SERENA_DASHBOARD_PORT", "24282"))
        with socket.create_connection((SERENA_HOST, port), timeout=PROBE_TIMEOUT_S):
            return True
    except (OSError, ValueError):
        return False


def transcript_mentions(transcript_path: str, needle: str) -> bool:
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
    # Only an actual Serena TOOL CALL counts, not a mention: the first user
    # turn of a session is one JSONL line that carries the deferred-tool list
    # (every mcp__serena__ name) next to the prompt text, which made the old
    # substring test believe Serena had already described every file the
    # prompt named (measured 2026-08-23, probe 2).
    return any(
        SERENA_CALL.search(line) is not None and needle in line.lower()
        for line in blob.splitlines()
    )


def line_count(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def grep_nudge(tool_input: dict) -> tuple[str, str] | None:
    pattern = tool_input.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        return None
    match = DEFINITION_PATTERN.search(pattern)
    if match is None:
        return None
    return (
        f"grep:{pattern}",
        f"Serena is running and this Grep ({pattern!r}) is a symbol lookup (keyword "
        f"{match.group(1)!r}). mcp__serena__find_symbol resolves through the language "
        "server and returns the definition with body and location; for call sites use "
        "mcp__serena__find_referencing_symbols. For a plain text search drop the keyword.",
    )


def read_nudge(tool_input: dict, transcript_path: str) -> tuple[str, str] | None:
    raw_path = tool_input.get("file_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return None
    path = Path(raw_path)
    if path.suffix.lower() not in SOURCE_SUFFIXES:
        return None
    lines = line_count(path)
    if lines <= WHOLE_FILE_LINE_THRESHOLD:
        return None
    if transcript_mentions(transcript_path, path.name):
        return None
    return (
        f"read:{path.name}",
        f"Serena is running and {path.name} is {lines} lines. "
        f"mcp__serena__get_symbols_overview(relative_path={path.name!r}) then "
        "mcp__serena__find_symbol(include_body=true) for the symbol you need is cheaper "
        "than the whole file. A targeted Read (offset/limit) is always fine.",
    )


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _advise(text: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }


def pre_tool(payload: dict, root: Path, sid: str, env: dict | None = None) -> HookResult:
    env = os.environ if env is None else env
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return HookResult()

    # Wrong-tree write guard: independent of the routing mode.
    if tool_name.startswith("mcp__serena__"):
        short = tool_name[len("mcp__serena__"):]
        if short in SERENA_WRITE_TOOLS:
            mismatch = serena_root_mismatch(root)
            if mismatch is not None:
                return HookResult(
                    payload=_deny(
                        f"Serena's configured project root is {mismatch}, but this session "
                        f"works in {root}. {tool_name} would edit the other tree "
                        "(incident 2026-08-22). Use Edit/Write/Bash with absolute paths in "
                        "this tree. Serena READ tools answer about the other tree "
                        "too, so they are not a safe substitute here."
                    ),
                    note="serena-write-mismatch",
                )
        return HookResult()

    mode = serena_mode(env)
    if mode == "off":
        return HookResult()
    if tool_name == "Grep":
        nudge = grep_nudge(tool_input)
    elif tool_name == "Read":
        nudge = read_nudge(tool_input, str(payload.get("transcript_path") or ""))
    else:
        return HookResult()
    if nudge is None:
        return HookResult()
    if serena_root_mismatch(root) is not None:
        # Reachability is not correctness: a server indexing another tree answers
        # confidently about code that is not here. Fail open to the native tools.
        return HookResult(note="serena-root-mismatch")
    if not serena_is_reachable(env):
        return HookResult(note="serena-unreachable")

    key, text = nudge
    if mode == "deny":
        return HookResult(payload=_deny(text), note="serena-deny")

    fresh: dict = {}

    def mutate(state: dict) -> None:
        advised = state.setdefault("serena_advised", [])
        fresh["new"] = key not in advised
        if fresh["new"]:
            advised.append(key)
            del advised[:-ADVISED_CAP]

    update_state(root, sid, mutate)
    if not fresh.get("new"):
        return HookResult(note="serena-advised-before")
    return HookResult(payload=_advise(text), note="serena-advise")


# --------------------------------------------------------------------------
# PostToolUse
# --------------------------------------------------------------------------


def post_tool(payload: dict, root: Path, sid: str) -> HookResult:
    """PostToolUse fires for calls that SUCCEEDED (failures raise
    PostToolUseFailure), so a test command seen here exited 0. A command that
    masks its own status (``pytest || true``) reaches here too -- which is why
    the recorded line carries the exact command text, so the reader can judge
    what "last test run" meant."""
    if str(payload.get("tool_name") or "") not in SHELL_TOOLS:
        return HookResult()
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return HookResult()

    notes: list[str] = []
    if TEST_COMMAND.search(command):
        fp = source_fingerprint(root)
        head = command.strip().splitlines()[0][:120]

        def mutate(state: dict) -> None:
            state["last_test"] = {
                "fp": fp,
                "cmd": head,
                "at": time.strftime("%H:%M"),
                "digest": sha256_text(repr(sorted(fp.items())))[:12],
            }

        update_state(root, sid, mutate)
        notes.append("test-run-recorded")

    if COMMIT_COMMAND.search(command) and "--dry-run" not in command:
        notes.append("commit-reminder")
        return HookResult(
            payload={
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": DOCS_DRIFT_REMINDER,
                }
            },
            note=",".join(notes),
        )
    return HookResult(note=",".join(notes))
