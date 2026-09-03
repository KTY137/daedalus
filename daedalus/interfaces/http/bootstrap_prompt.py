"""Session bootstrap prompts for external runtimes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ... import core
from ...foundation.projects import load_project

HARNESS_ROOT = Path(__file__).resolve().parents[3]


def claude_bootstrap_prompt(project: str) -> dict[str, Any]:
    pdata = load_project(project)
    repo_root = pdata["repo_root"]
    team = core.team_config(project)
    active_agents = ", ".join(team.get("active_agents") or []) or "none configured"
    text = f"""This repository is connected to the Daedalus Agent OS harness.

Harness root:
{HARNESS_ROOT}

Project:
{project}

Project repository:
{repo_root}

Your role:
- Treat Claude Code as the trusted frontier/senior runtime.
- Use Daedalus/Ikarus for delegation, routing, local Ollama workers, queue state, and policy.
- Do not invent direct agent-to-agent messages. Use the file bus and Daedalus commands.

Useful commands:
```powershell
cd "{HARNESS_ROOT}"
python -m daedalus.interfaces.cli.entry dashboard --project {project} --json
python -m daedalus.interfaces.cli.entry spawn "<objective>" --project {project}
python -m daedalus.file_bridge enqueue "<task>" --project {project} --lane local_only --source claude
python -m daedalus.file_bridge enqueue "<task>" --project {project} --lane auto --source claude
python -m daedalus.file_bridge watch --project {project}
```

Where to read results:
- Queue requests: {HARNESS_ROOT / "outbox"}
- Reports: {HARNESS_ROOT / "inbox"}
- Recovery memory: {HARNESS_ROOT / "memory" / "todos.local.md"}
- Agent OS app: http://127.0.0.1:8765/

Current active Daedalus agents:
{active_agents}

Safety:
- Respect project policy in projects/{project}.json and repo-local .agentenv/.
- Do not run code that can touch real hardware unless the user explicitly scopes it.
- Prefer local_only while cloud tokens are constrained.
- Escalate high-risk writes through visible queue/policy rather than silent autonomous edits.
"""
    return {"project": project, "prompt": text}
