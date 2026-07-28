"""Mirror this Claude Code session into Der Raum, live.

Claude Code fires hooks around a turn. This script is that hook: it reads the
hook payload on stdin and appends the human's prompt or Claude's reply to the
shared room file, so the other vendors' agents see the conversation as it
happens instead of being told about it afterwards.

Wire it in settings.json:

  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command",
       "command": "python <repo>/runs/council/stream_hook.py user"}]}],
    "Stop":            [{"hooks": [{"type": "command",
       "command": "python <repo>/runs/council/stream_hook.py assistant"}]}]
  }

Design constraints that matter:
- NEVER fail the turn. A hook that raises blocks the session, so every error
  path exits 0 silently. A broken mirror must not break the conversation.
- Skip empty and duplicate turns: Stop can fire more than once around
  sub-agent activity, and a room full of repeats is worse than no mirror.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOM = Path(__file__).resolve().parent / "room.md"
SEEN = Path(__file__).resolve().parent / ".stream_seen"
MAX_CHARS = 4000


def _dedupe(text: str) -> bool:
    """True if this exact text was already mirrored (keeps the last 40)."""
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
    try:
        seen = SEEN.read_text(encoding="utf-8").split()
    except OSError:
        seen = []
    if digest in seen:
        return True
    seen.append(digest)
    try:
        SEEN.write_text("\n".join(seen[-40:]), encoding="utf-8")
    except OSError:
        pass
    return False


def _append(name: str, tag: str, text: str) -> None:
    text = text.strip()
    if not text or _dedupe(text):
        return
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n\n_[trimmed at {MAX_CHARS} chars for the room]_"
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    ROOM.parent.mkdir(parents=True, exist_ok=True)
    with ROOM.open("a", encoding="utf-8") as fh:
        fh.write(f"\n---\n\n### {name}  ·  {tag}  ·  {stamp}\n\n{text}\n")


def _extract(payload: dict, role: str) -> str:
    """Pull the turn text out of whatever shape the hook payload has."""
    if role == "user":
        for key in ("prompt", "user_prompt", "message", "text"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ""
    # assistant: prefer an explicit field, else the last assistant message
    for key in ("response", "assistant_response", "last_message", "text"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    msgs = payload.get("messages")
    if isinstance(msgs, list):
        for msg in reversed(msgs):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if any(parts):
                        return "\n".join(p for p in parts if p)
    return ""


def main() -> int:
    role = sys.argv[1] if len(sys.argv) > 1 else "user"
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        text = _extract(payload, role)
        if role == "user":
            _append("Kaya", "human · live", text)
        else:
            _append("Claude", "Anthropic · Fable 5 · live", text)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
