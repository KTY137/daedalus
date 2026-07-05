"""Portable per-repo config resolution.

To run the bench against ANY repo, the safety policy travels *with that repo*.
Resolution order:
  1. explicit --project from the registry (projects/<name>.json), else
  2. a repo-local `.agentenv/agentenv.json` in the target repo, else
  3. None -> fail-closed: the bench may read/advise but never write.

The file shape mirrors a project entry: {"policy": {...}, "test_command", "test_cwd"}.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_CONFIG = ".agentenv/agentenv.json"

STARTER: dict = {
    "_comment": "agent_env policy for THIS repo. Generic secret protections are "
                "always merged in; add your own denies. With no 'policy' block, "
                "the bench is read/advise-only (fail-closed). Edit, then run `agentenv doctor`.",
    "policy": {
        "deny": ["secret", "credential", ".env", "id_rsa", ".pem"],
        "allow": ["docs/", "/tests/", "test_", ".md", "readme"],
        "allow_exceptions": ["_simulated.py"],
        "high_risk_paths": [],
        "high_risk_terms": ["delete", "drop table", "migration", "auth",
                            "payment", "production", "deploy"],
        "deny_content": []
    },
    "test_command": "python -m pytest -q",
    "test_cwd": "."
}


def resolve_project(repo_root: str, project: str | None = None) -> dict | None:
    """Return a project-config dict (with a 'policy' block) or None."""
    if project:
        from .projects import load_project
        return load_project(project)
    f = Path(repo_root) / REPO_CONFIG
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        data.setdefault("repo_root", str(Path(repo_root).resolve()))
        return data
    return None


def init_repo(repo_root: str) -> str:
    """Scaffold `.agentenv/agentenv.json` in a repo. Returns the path written."""
    d = Path(repo_root) / ".agentenv"
    d.mkdir(exist_ok=True)
    f = d / "agentenv.json"
    if not f.exists():
        f.write_text(json.dumps(STARTER, indent=2), encoding="utf-8")
    return str(f)
