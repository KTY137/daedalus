#!/usr/bin/env python3
"""Fail-closed process wrapper for the Iron Plan lifecycle hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools" / "iron_plan_guard.py"


def _valid_guard_output(value: object, event: str) -> bool:
    if not isinstance(value, dict):
        return False
    if event == "Stop":
        return (
            value.get("decision") == "block"
            and isinstance(value.get("reason"), str)
            and bool(value["reason"].strip())
        )

    specific = value.get("hookSpecificOutput")
    if not isinstance(specific, dict):
        return False
    if specific.get("hookEventName") != (event or "SessionStart"):
        return False
    decision = specific.get("permissionDecision")
    if decision is not None:
        return (
            event == "PreToolUse"
            and decision == "deny"
            and isinstance(specific.get("permissionDecisionReason"), str)
            and bool(specific["permissionDecisionReason"].strip())
        )
    context = specific.get("additionalContext")
    return isinstance(context, str) and bool(context.strip())


def main() -> int:
    payload = sys.stdin.buffer.read()
    event = ""
    try:
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            event = str(
                decoded.get("hook_event_name")
                or decoded.get("hookEventName")
                or ""
            )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        pass

    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(GUARD),
                "--repo-root",
                str(ROOT),
                "hook",
            ],
            input=payload,
            capture_output=True,
            timeout=8,
            check=False,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Iron Plan hook runner failed closed: {exc}", file=sys.stderr)
        return 2

    if proc.returncode != 0:
        if proc.stderr:
            sys.stderr.write(proc.stderr.decode("utf-8", errors="replace"))
        else:
            print(
                f"Iron Plan guard exited {proc.returncode}; failing closed",
                file=sys.stderr,
            )
        return 2

    if proc.stdout:
        try:
            decoded_output = json.loads(proc.stdout)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            print("Iron Plan guard emitted invalid JSON; failing closed", file=sys.stderr)
            return 2
        if not _valid_guard_output(decoded_output, event):
            print(
                "Iron Plan guard emitted an invalid event decision; failing closed",
                file=sys.stderr,
            )
            return 2
    elif event != "Stop":
        print(
            f"Iron Plan guard emitted no decision/context for {event or 'unknown event'}; "
            "failing closed",
            file=sys.stderr,
        )
        return 2

    sys.stdout.write(proc.stdout.decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
