"""Detect Claude Code subagents defined in a repo's `.claude/agents/`.

These are distinct from the harness's own agent roles (`agents/*.json`, which
Ikarus routes offload work to): a `.claude/agents/<name>.md` file is a Claude
Code subagent — the frontier crew that builds the app itself. Mission Control
surfaces them *additionally* so both crews are visible in one cockpit.

Frontmatter is parsed with the stdlib only (the package has no yaml runtime
dependency): a minimal reader for the top-level scalar keys we care about
(`name`, `description`, `model`, `tools`), tolerant of single-line values and
folded/literal blocks (`description: >`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_BLOCK_MARKERS = (">", "|", ">-", "|-", ">+", "|+", "")


def parse_frontmatter(text: str) -> dict[str, str]:
    """Return the top-level scalar keys from a leading `---`/`---` YAML block.
    Best-effort and dependency-free; unknown/complex YAML is skipped, not raised."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    lines = text[3:end].strip("\n").split("\n")
    data: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = _KEY_RE.match(line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in _BLOCK_MARKERS:
            # folded/literal or empty scalar: gather following more-indented lines
            collected: list[str] = []
            j = i + 1
            while j < len(lines) and (lines[j][:1] in (" ", "\t") or not lines[j].strip()):
                if lines[j].strip():
                    collected.append(lines[j].strip())
                j += 1
            val = " ".join(collected)
            i = j
        else:
            val = val.strip().strip('"').strip("'")
            i += 1
        data[key] = val
    return data


def detect_claude_crew(repo_root: str | None) -> dict[str, Any]:
    """Scan `<repo_root>/.claude/agents/*.md` and return the Claude Code
    subagents found there (name, description, model, tools, source path)."""
    agents: list[dict[str, Any]] = []
    if repo_root:
        d = Path(repo_root) / ".claude" / "agents"
        if d.is_dir():
            for path in sorted(d.glob("*.md")):
                try:
                    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
                except OSError:
                    continue
                agents.append({
                    "name": fm.get("name") or path.stem,
                    "description": fm.get("description", ""),
                    "model": fm.get("model", "inherit"),
                    "tools": fm.get("tools", ""),
                    "source": str(path),
                })
    return {"agents": agents, "count": len(agents)}
