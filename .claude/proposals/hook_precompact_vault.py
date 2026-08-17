#!/usr/bin/env python3
"""Proposed PreCompact hook: log an audit line to the vault daily note.

Before every context compaction (manual or auto) this appends one line to
vault/Sessions/<YYYY-MM-DD>.md so a compaction never erases context without a
trace a human can follow. It NEVER blocks compaction (always exit 0) and it
never edits existing lines (append-only, vault convention).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    cwd = data.get("cwd") or "."
    vault_sessions = Path(cwd) / "vault" / "Sessions"
    if not vault_sessions.parent.is_dir():
        return 0  # not this repo; do nothing

    now = datetime.datetime.now()
    note = vault_sessions / f"{now:%Y-%m-%d}.md"
    trigger = data.get("compaction_trigger", "unknown")
    transcript = data.get("transcript_path", "")
    session = data.get("session_id", "")[:8]

    line = (
        f"- {now:%H:%M} [compaction:{trigger}] Kontext kompaktiert "
        f"(Session {session}) — Transkript: `{transcript}`\n"
    )
    try:
        vault_sessions.mkdir(parents=True, exist_ok=True)
        if not note.exists():
            header = (
                f"---\ntags: [session]\ndate: {now:%Y-%m-%d}\n---\n\n"
                f"# Session {now:%Y-%m-%d}\n\n## Kompaktierungen\n\n"
            )
            note.write_text(header + line, encoding="utf-8", newline="\n")
        else:
            with note.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
    except Exception:
        pass  # never break compaction over a diary entry
    return 0


if __name__ == "__main__":
    sys.exit(main())
