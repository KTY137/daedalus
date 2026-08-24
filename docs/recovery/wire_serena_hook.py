"""Wire the serena-first hook into the session settings (amendment 003, enforcement part).

Owner-approved 2026-08-05 (proposal 003), owner-directed today ("harte hooks
einführen"). Adds one PreToolUse entry matching Read|Grep that runs the
fail-open serena-first hook. The token travels via the environment to git's
hooks, which enforce the protected-file rule.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\nukei\Desktop\agent_env")
SETTINGS = ROOT / ".claude" / "settings.json"
TOKEN = "a47d84ee736fcaebd76f4309f4e0653f536415b9bda9e04940920ca1896026d4"

raw = SETTINGS.read_bytes().decode("utf-8")
cfg = json.loads(raw)

pre = cfg["hooks"]["PreToolUse"]
if any("serena-first" in json.dumps(entry) for entry in pre):
    print("already wired; nothing to do")
    sys.exit(0)

pre.append({
    "matcher": "Read|Grep",
    "hooks": [
        {
            "type": "command",
            "command": 'python "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/serena-first.py"',
            "timeout": 10,
            "statusMessage": "Routing symbol work through Serena...",
        }
    ],
})

SETTINGS.write_bytes(json.dumps(cfg, indent=2).encode("utf-8"))
print("settings updated: PreToolUse Read|Grep -> serena-first.py")

msg = Path(__file__).parent / "msg_serena_wire.txt"
env = dict(os.environ, DAEDALUS_IRON_PLAN_AMENDMENT=TOKEN)
r1 = subprocess.run(["git", "-C", str(ROOT), "add", ".claude/settings.json"],
                    env=env, capture_output=True, text=True)
r2 = subprocess.run(["git", "-C", str(ROOT), "commit", "-F", str(msg)],
                    env=env, capture_output=True, text=True)
print("add rc:", r1.returncode, r1.stderr[-200:] if r1.returncode else "")
print("commit rc:", r2.returncode)
print((r2.stdout or r2.stderr)[-400:])
sys.exit(r2.returncode)
