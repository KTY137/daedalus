#!/usr/bin/env python3
"""Proposed Notification hook: Windows popup when Claude needs the owner.

Fires on notification types where an unattended run is stalled or done
(permission_prompt, agent_needs_input, agent_completed). Uses WScript.Shell
via PowerShell — no extra module, auto-dismisses after 6 seconds.
Notification hooks cannot block anything; this is purely additive UX.
"""

from __future__ import annotations

import json
import subprocess
import sys

INTERESTING = {
    "permission_prompt": "Claude wartet auf eine Permission-Entscheidung",
    "agent_needs_input": "Ein Agent braucht Input",
    "agent_completed": "Ein Agent ist fertig",
}


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    kind = data.get("notification_type", "")
    text = INTERESTING.get(kind)
    if not text:
        return 0

    ps = (
        "(New-Object -ComObject Wscript.Shell)"
        f".Popup('{text}', 6, 'Claude Code — Daedalus', 64)"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=8,
            capture_output=True,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
