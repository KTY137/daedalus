#!/usr/bin/env python3
"""User-level orientation hook: which tree is this session standing in?

Registered in ~/.claude/settings.json on SessionStart (startup|resume|clear|
compact|fork) and CwdChanged. Reads ~/.claude/hooks/roots.json:

    {"live": ["C:/Users/me/Desktop/agent_env_g0"],
     "archived": {"C:/Users/me/Desktop/agent_env": "archive/checkpoint-2026-07-20-session"}}

and says ONE thing when the session's repository is a listed root: that it is
the live tree, or that it is an archived one (naming the live tree to work in).
For any other directory it says nothing -- most projects are not Daedalus.

Why user-level: a repository's own hooks cannot warn about that repository
being archived (the archived tree's settings are frozen with it, Codex review
B3, 2026-08-23). The list of roots is a fact about this machine, so it lives
with the user, not in a repo. Stdlib only, no jq, exits 0 on every path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOTS_FILE = Path(__file__).resolve().with_name("roots.json")


def _norm(p: str) -> str:
    try:
        text = str(Path(p).resolve())
    except OSError:
        text = str(p)
    text = text.replace("\\", "/").rstrip("/")
    return text.lower() if os.name == "nt" else text


def _toplevel(cwd: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        return out.stdout.strip() if out.returncode == 0 else cwd
    except (OSError, subprocess.SubprocessError):
        return cwd


def classify(cwd: str, roots: dict) -> str:
    """The one line to say, or ""."""
    here = _norm(_toplevel(cwd))
    live_raw = roots.get("live")
    live = [_norm(p) for p in live_raw if isinstance(p, str)] if isinstance(live_raw, list) else []
    arch_raw = roots.get("archived")
    archived = (
        {_norm(p): str(tag) for p, tag in arch_raw.items() if isinstance(p, str)}
        if isinstance(arch_raw, dict) else {}
    )
    if here in live:
        return f"ROOT: live tree ({Path(here).name})"
    if here in archived:
        live_hint = f"; work belongs in {live_raw[0]}" if live else ""
        tag = archived[here]
        return (
            f"ROOT: ARCHIVED tree ({Path(here).name}, {tag}) -- history only, do not edit here"
            f"{live_hint}. Serena/MCP servers of this session index the archived tree."
        )
    return ""


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return 0
    try:
        roots = json.loads(ROOTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    line = classify(cwd, roots if isinstance(roots, dict) else {})
    if not line:
        return 0
    event = payload.get("hook_event_name", "")
    if event == "SessionStart":
        print(line)  # plain stdout becomes context for SessionStart
    else:
        print(json.dumps({
            "systemMessage": line,
            "hookSpecificOutput": {"hookEventName": event or "CwdChanged", "additionalContext": line},
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
