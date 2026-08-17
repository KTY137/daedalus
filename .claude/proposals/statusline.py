#!/usr/bin/env python3
"""Proposed Claude Code statusline — pure stdlib, no jq (not installed here).

Reads the session JSON from stdin (see code.claude.com/docs/en/statusline)
and prints one line: [Model] dir | branch | ctx nn% | $cost.
Fails soft: any error still prints a minimal line, never crashes the UI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

DIM = "\033[2m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def git_branch(cwd: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", cwd or ".", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("[Claude]")
        return

    model = (data.get("model") or {}).get("display_name", "?")
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd") or ""
    directory = os.path.basename(cwd.rstrip("\\/")) or "?"
    parts = [f"[{model}] {directory}"]

    branch = git_branch(cwd)
    if branch:
        parts.append(branch)

    ctx = (data.get("context_window") or {}).get("used_percentage")
    if isinstance(ctx, (int, float)):
        if ctx >= 85:
            parts.append(f"{RED}ctx {ctx:.0f}%{RESET}")
        elif ctx >= 60:
            parts.append(f"{YELLOW}ctx {ctx:.0f}%{RESET}")
        else:
            parts.append(f"ctx {ctx:.0f}%")

    cost = (data.get("cost") or {}).get("total_cost_usd")
    if isinstance(cost, (int, float)) and cost > 0:
        parts.append(f"${cost:.2f}")

    print(f" {DIM}|{RESET} ".join(parts))


if __name__ == "__main__":
    main()
