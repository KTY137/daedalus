"""Owner-run kit: give the Serena MCP server time to boot (MCP_TIMEOUT).

MEASURED 2026-08-21: serena.exe boots THREE language servers (python,
typescript, rust). Known cold start ~28.35s vs the 30s default MCP client
startup timeout; today's log (~/.serena/logs/2026-08-21/mcp_20260821-204215_2340.txt)
shows the client shutting the server down 3s into LSP startup. Result:
whole sessions run with zero semantic retrieval.

Fix: MCP_TIMEOUT=120000 in .claude/settings.local.json (machine-specific
timing, untracked, layers over project settings). The guard classifier
blocks agent writes to harness settings, so the owner runs this by hand:

    python docs/recovery/serena_mcp_timeout_kit.py

Idempotent; preserves every existing key. Related, still pending separately:
docs/recovery/wire_serena_hook.py (amendment 003 enforcement half — the
serena-first PreToolUse hook exists at .claude/hooks/serena-first.py but was
never wired into settings.json).
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\nukei\Desktop\agent_env")
SETTINGS = ROOT / ".claude" / "settings.local.json"

cfg = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
env = cfg.setdefault("env", {})

if env.get("MCP_TIMEOUT") == "120000":
    print("already set; nothing to do")
    sys.exit(0)

before = env.get("MCP_TIMEOUT")
env["MCP_TIMEOUT"] = "120000"
SETTINGS.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
print(f"MCP_TIMEOUT: {before!r} -> '120000' in {SETTINGS}")
print("Takes effect on the NEXT Claude Code session start (MCP servers connect at startup).")
