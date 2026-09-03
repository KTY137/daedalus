"""Runtime CRUD for agent-role definitions — Ikarus as a dynamic configurator.

Roles are the SAME JSON the router reads via ``router.load_agents``. Writing
here lets Ikarus / the CLI / the GUI mint or edit roles at runtime; routing
picks them up with no other change because ``load_agents`` is the single read
path.

Write location mirrors the read resolution in ``router``:
  - ``repo_root`` given -> ``<repo_root>/.agentenv/agents/<name>.json`` (created
    on demand; a per-repo override that never mutates the shipped templates).
  - ``repo_root`` None  -> rejected because packaged defaults are read-only.

``templates/agents/`` (the shipped defaults) is never written to here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..router import load_agents

MODEL_TIERS = ("opus", "sonnet", "haiku")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
# Names that collide with non-role config files in an agent dir (see
# router._NON_ROLE_FILES): a role so named would be silently skipped by
# load_agents, so reject it at creation instead of losing it without a trace.
_RESERVED_ROLE_NAMES = {"categories"}
_LIST_FIELDS = ("owns", "triggers", "must_read")


def _write_dir_for(repo_root: str | None) -> Path:
    """Where a NEW/edited role is written (never the shared templates dir)."""
    if repo_root:
        return Path(repo_root) / ".agentenv" / "agents"
    raise ValueError("repo_root is required; packaged agent defaults are read-only")


def role_path(name: str, repo_root: str | None = None) -> Path:
    return _write_dir_for(repo_root) / f"{name}.json"


def validate_role(role: dict[str, Any]) -> list[str]:
    """Fail-closed validation. Returns a list of human-readable errors ([] = ok)."""
    errors: list[str] = []
    name = role.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name or ""):
        errors.append("name must be a lowercase slug (a-z, 0-9, '-'), 2-41 chars")
    elif name in _RESERVED_ROLE_NAMES:
        errors.append(f"'{name}' is a reserved name (collides with a non-role config file)")
    if role.get("model_tier", "sonnet") not in MODEL_TIERS:
        errors.append(f"model_tier must be one of {', '.join(MODEL_TIERS)}")
    if not isinstance(role.get("external_ok", False), bool):
        errors.append("external_ok must be a boolean")
    for field in _LIST_FIELDS:
        val = role.get(field, [])
        if not (isinstance(val, list) and all(isinstance(x, str) for x in val)):
            errors.append(f"{field} must be a list of strings")
    if not isinstance(role.get("output_schema", "agent_report_v1"), str) or not role.get("output_schema", "agent_report_v1"):
        errors.append("output_schema must be a non-empty string")
    if not isinstance(role.get("call_name", ""), str):
        errors.append("call_name must be a string")
    if not isinstance(role.get("category", ""), str):
        errors.append("category must be a string")
    return errors


def normalize_role(role: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults so a partial spec becomes a complete, stably-ordered role."""
    return {
        "name": role["name"],
        "call_name": role.get("call_name", ""),
        "model_tier": role.get("model_tier", "sonnet"),
        "external_ok": bool(role.get("external_ok", False)),
        "owns": list(role.get("owns", [])),
        "triggers": list(role.get("triggers", [])),
        "must_read": list(role.get("must_read", [])),
        "output_schema": role.get("output_schema", "agent_report_v1"),
        "category": role.get("category", ""),
    }


def list_roles(repo_root: str | None = None) -> list[dict[str, Any]]:
    return load_agents(repo_root)


def get_role(name: str, repo_root: str | None = None) -> dict[str, Any] | None:
    return next((a for a in load_agents(repo_root) if a.get("name") == name), None)


def create_role(role: dict[str, Any], repo_root: str | None = None, *, overwrite: bool = False) -> Path:
    errors = validate_role(role)
    if errors:
        raise ValueError("; ".join(errors))
    path = role_path(role["name"], repo_root)
    if path.exists() and not overwrite:
        raise FileExistsError(f"agent '{role['name']}' already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_role(role), indent=2), encoding="utf-8")
    return path


def update_role(name: str, patch: dict[str, Any], repo_root: str | None = None) -> Path:
    """Merge ``patch`` over the current role and rewrite. For a role that lives
    only in the shipped templates, this writes a per-repo override (never
    mutating the template)."""
    current = get_role(name, repo_root)
    if current is None:
        raise KeyError(f"unknown agent '{name}'")
    merged = {**current, **patch, "name": name}
    errors = validate_role(merged)
    if errors:
        raise ValueError("; ".join(errors))
    path = role_path(name, repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_role(merged), indent=2), encoding="utf-8")
    return path


def delete_role(name: str, repo_root: str | None = None) -> bool:
    """Delete a role from the writable dir. Returns False if it isn't there
    (e.g. it's a shipped template default, which cannot be deleted, only
    overridden)."""
    path = role_path(name, repo_root)
    if path.exists():
        path.unlink()
        return True
    return False
