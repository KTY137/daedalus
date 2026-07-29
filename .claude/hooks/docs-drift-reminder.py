#!/usr/bin/env python
"""PostToolUse hook: after a successful `git commit`, remind the session to bring
docs/handoff back in sync in the SAME beat as the structural change.

Deterministic trigger for the chronicler role (mnemosyne) so doc upkeep does not
depend on the model remembering. Emits additionalContext; never blocks.

Reads the hook payload as JSON on stdin. Exits 0 and prints nothing when the
tool call was not a real commit.
"""

import json
import sys

REMINDER = (
    "A commit just landed. If it changed structure, interfaces, or any number that "
    "appears in docs, dispatch the mnemosyne delegate now to bring HANDOFF/docs/status "
    "back in sync and stamp provenance (MEASURED / INHERITED / ASSUMED). If the commit "
    "was cosmetic (formatting, comments, test-only churn), skip it and say so in one clause."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if "git commit" not in command or "--dry-run" in command:
        return 0

    # Nothing landed, nothing to document.
    if (payload.get("tool_response") or {}).get("is_error") is True:
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": REMINDER,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
