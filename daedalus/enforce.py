# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import init_repo
from .projects import resolve_repo_root


BEGIN = "<!-- AGENT_ENV_ENFORCED:BEGIN -->"
END = "<!-- AGENT_ENV_ENFORCED:END -->"


def _block(project: str | None, tool: str) -> str:
    project_arg = f"--project {project}" if project else "--repo-root <this repo>"
    local_only = (
        f"python -m daedalus.file_bridge enqueue \"<task>\" {project_arg} "
        "--lane local_only --source "
    )
    auto = (
        f"python -m daedalus.file_bridge enqueue \"<task>\" {project_arg} "
        "--lane auto --source "
    )
    return f"""{BEGIN}

## Daedalus Enforcement

This repository is managed by the external `daedalus` harness. When delegating
work, use the harness file bus instead of direct agent-to-agent messages.

- Token-safe local path:

  ```powershell
  {local_only}{tool}
  ```

- Normal routed path:

  ```powershell
  {auto}{tool}
  ```

- The watcher must be running:

  ```powershell
  python -m daedalus.file_bridge watch {project_arg}
  ```

Rules:
- Prefer `local_only` while Claude tokens are exhausted.
- Do not bypass Ikarus for local/Ollama work.
- Read reports from `C:\\Users\\nukei\\Desktop\\agent_env\\inbox`.
- Check recovery memory at `C:\\Users\\nukei\\Desktop\\agent_env\\memory\\todos.local.md`.

{END}
"""


def _replace_or_append(text: str, block: str) -> str:
    start = text.find(BEGIN)
    end = text.find(END)
    if start != -1 and end != -1 and end > start:
        return text[:start].rstrip() + "\n\n" + block.rstrip() + "\n" + text[end + len(END):].lstrip()
    if text and not text.endswith("\n"):
        text += "\n"
    return text.rstrip() + "\n\n" + block.rstrip() + "\n"


def _enforce_file(repo_root: Path, filename: str, project: str | None, source: str) -> str:
    path = repo_root / filename
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {filename}\n"
    updated = _replace_or_append(existing, _block(project, source))
    path.write_text(updated, encoding="utf-8")
    return str(path)


def enforce_repo(repo_root: str, project: str | None = None) -> dict:
    root = Path(repo_root).resolve()
    init_repo(str(root))
    touched = [
        _enforce_file(root, "AGENTS.md", project, "codex"),
        _enforce_file(root, "CLAUDE.md", project, "claude"),
    ]

    daedalus = root / ".agentenv"
    daedalus.mkdir(exist_ok=True)
    state_path = daedalus / "enforcement.json"
    state = {
        "enabled": True,
        "project": project,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "files": touched,
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    touched.append(str(state_path))
    return {"repo_root": str(root), "project": project, "enforced": True, "files": touched}


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce daedalus harness instructions in a repo.")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    args = parser.parse_args()
    repo_root = resolve_repo_root(args.repo_root, args.project)
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.enforce",
        REGISTRY_BY_ID["cli.enforce"].effects,
        (process_guard_boundary_decision(),),
    )
    print(json.dumps(enforce_repo(repo_root, args.project), indent=2))


if __name__ == "__main__":
    main()
