"""Control-plane projection for Daedalus + Claude Code projects.

The app is not a Claude Code replacement. It reads and writes the source files
Claude Code and Daedalus already use, then presents one coherent operating
model: unified agents, capabilities, autonomy policy, and Claude config status.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import core
from .claude_detect import detect_claude_crew
from .projects import (
    ProjectRegistryUnavailable,
    ProjectRowUpdateError,
    load_project,
    rewrite_project_team,
)
from .router import load_agents

AUTONOMY_MODES = ("manual", "semi_auto", "autonomous")
_MODE_RANK = {mode: i for i, mode in enumerate(AUTONOMY_MODES)}

CAPABILITY_GATES: list[dict[str, Any]] = [
    {"id": "read_files", "label": "Read files", "default": "semi_auto", "critical": False},
    {"id": "file_write", "label": "Write files", "default": "manual", "critical": True},
    {"id": "bash", "label": "Run shell commands", "default": "manual", "critical": True},
    {"id": "mcp_read", "label": "Read via MCP", "default": "semi_auto", "critical": False},
    {"id": "mcp_write", "label": "Write via MCP", "default": "manual", "critical": True},
    {"id": "external_api", "label": "External APIs", "default": "manual", "critical": True},
    {"id": "claude_escalate", "label": "Escalate to Claude", "default": "manual", "critical": True},
    {"id": "ollama_write", "label": "Local verified write", "default": "semi_auto", "critical": False},
    {"id": "codex_delegate", "label": "Delegate through Codex", "default": "semi_auto", "critical": False},
    {"id": "codex_write", "label": "Codex code writes", "default": "manual", "critical": True},
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"_error": f"unable to parse {path}"}
    return data if isinstance(data, dict) else {"_error": f"{path} is not a JSON object"}


def _repo_root(project: str) -> Path:
    return Path(str(load_project(project)["repo_root"]))


def _norm_mode(value: Any, fallback: str = "manual") -> str:
    mode = str(value or fallback)
    return mode if mode in AUTONOMY_MODES else fallback


def claude_surface(project: str) -> dict[str, Any]:
    root = _repo_root(project)
    settings = _read_json(root / ".claude" / "settings.json")
    local_settings = _read_json(root / ".claude" / "settings.local.json")
    mcp = _read_json(root / ".mcp.json")
    crew = detect_claude_crew(str(root))
    permissions = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    mcp_servers = mcp.get("mcpServers") if isinstance(mcp.get("mcpServers"), dict) else {}
    return {
        "repo_root": str(root),
        "subagents": crew["agents"],
        "subagent_count": crew["count"],
        "settings": {
            "path": str(root / ".claude" / "settings.json"),
            "exists": (root / ".claude" / "settings.json").exists(),
            "defaultMode": settings.get("defaultMode") or settings.get("permissionMode") or "",
            "permissions": {
                "allow": list(permissions.get("allow") or []),
                "ask": list(permissions.get("ask") or []),
                "deny": list(permissions.get("deny") or []),
            },
            "hooks": hooks,
            "errors": [settings.get("_error")] if settings.get("_error") else [],
        },
        "local_settings": {
            "path": str(root / ".claude" / "settings.local.json"),
            "exists": (root / ".claude" / "settings.local.json").exists(),
            "errors": [local_settings.get("_error")] if local_settings.get("_error") else [],
        },
        "mcp": {
            "path": str(root / ".mcp.json"),
            "exists": (root / ".mcp.json").exists(),
            "servers": [{"name": name, **(spec if isinstance(spec, dict) else {"value": spec})} for name, spec in mcp_servers.items()],
            "errors": [mcp.get("_error")] if mcp.get("_error") else [],
        },
        "extensions": {
            "slash_commands": {"status": "runtime-discovered", "note": "Available through Claude Agent SDK init messages."},
            "skills_plugins": {"status": "planned", "note": "Will be linked to agent profiles after plugin discovery is wired."},
            "checkpoints": {"status": "runtime", "note": "Claude Code owns checkpoint execution; Daedalus surfaces status and launch actions."},
            "background_tasks": {"status": "runtime", "note": "Claude Code owns long-running task execution; Daedalus monitors process state."},
        },
    }


def codex_surface(project: str) -> dict[str, Any]:
    root = _repo_root(project)
    agents_md = root / "AGENTS.md"
    text = ""
    try:
        text = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
    except OSError:
        text = ""
    return {
        "repo_root": str(root),
        "agents_md": {
            "path": str(agents_md),
            "exists": agents_md.exists(),
            "managed": "AGENT_ENV_ENFORCED:BEGIN" in text and "AGENT_ENV_ENFORCED:END" in text,
            "mentions_harness": "file_bridge" in text or "agent_env" in text or "daedalus" in text,
        },
        "runtime": {
            "role": "coding collaborator and harness client",
            "communication": "file_bus",
            "queue_source": "codex",
            "contract": "Use AGENTS.md instructions; do not message Claude directly.",
        },
        "features": {
            "instructions": "AGENTS.md",
            "handoff": "outbox/inbox file bus",
            "reviews": "daedalus review-diff / queue local_only",
            "implementation": "direct workspace edits with Daedalus policy awareness",
        },
    }


def _capabilities_for(role: dict[str, Any], subagent: dict[str, Any] | None) -> list[str]:
    caps = ["read_files", "ollama_write", "claude_escalate", "codex_delegate"]
    if role.get("external_ok"):
        caps.append("external_api")
    tools = str((subagent or {}).get("tools") or "")
    if any(t in tools for t in ("Edit", "Write", "MultiEdit")):
        caps.append("file_write")
    if "Bash" in tools:
        caps.append("bash")
    if "mcp__" in tools:
        caps.append("mcp_read")
    return list(dict.fromkeys(caps))


def _sync_status(role: dict[str, Any] | None, subagent: dict[str, Any] | None) -> str:
    if role and subagent:
        claude_model = str(subagent.get("model") or "inherit")
        role_tier = str(role.get("model_tier") or "")
        if claude_model not in ("", "inherit") and role_tier and claude_model != role_tier:
            return "drift"
        return "unified"
    if role:
        return "daedalus_only"
    return "claude_only"


def _autonomy_config(project_data: dict[str, Any]) -> dict[str, Any]:
    team = project_data.get("team") or {}
    autonomy = team.get("autonomy") if isinstance(team.get("autonomy"), dict) else {}
    return {
        "default": _norm_mode(autonomy.get("default"), "manual"),
        "agents": dict(autonomy.get("agents") or {}),
        "capabilities": dict(autonomy.get("capabilities") or {}),
    }


def resolve_autonomy(project_data: dict[str, Any], agent_name: str, capability: str) -> dict[str, Any]:
    autonomy = _autonomy_config(project_data)
    gate = next((g for g in CAPABILITY_GATES if g["id"] == capability), {"default": "manual", "critical": True})
    project_mode = _norm_mode(autonomy["default"], "manual")
    agent_mode = _norm_mode(autonomy["agents"].get(agent_name), project_mode)
    capability_mode = _norm_mode(autonomy["capabilities"].get(capability), str(gate["default"]))
    # Use the most restrictive applicable mode. Critical defaults therefore
    # stay confirmation-first unless the project explicitly relaxes them.
    resolved = min((project_mode, agent_mode, capability_mode), key=lambda m: _MODE_RANK[m])
    return {
        "mode": resolved,
        "project_default": project_mode,
        "agent_override": agent_mode if agent_name in autonomy["agents"] else "",
        "capability_gate": capability_mode,
        "requires_confirmation": resolved == "manual" or bool(gate.get("critical") and capability_mode == "manual"),
        "critical": bool(gate.get("critical")),
    }


def unified_profiles(project: str) -> dict[str, Any]:
    project_data = load_project(project)
    root = Path(str(project_data["repo_root"]))
    roles = {a.get("name"): a for a in load_agents(str(root))}
    claude = claude_surface(project)
    subagents = {a.get("name"): a for a in claude["subagents"]}
    team = core.team_config(project)
    codex = codex_surface(project)
    categories = {c["id"]: c for c in core.get_categories(project).get("categories", [])}
    names = sorted(set(roles) | set(subagents))
    profiles = []
    for name in names:
        role = roles.get(name)
        subagent = subagents.get(name)
        category = (role or {}).get("category", "")
        caps = _capabilities_for(role or {}, subagent)
        profiles.append({
            "name": name,
            "display_name": (role or {}).get("call_name") or (subagent or {}).get("name") or name,
            "sync_status": _sync_status(role, subagent),
            "daedalus": role,
            "claude": subagent,
            "category": category,
            "category_label": (categories.get(category) or {}).get("name", category),
            "squads": [squad for squad, members in (team.get("squads") or {}).items() if name in members],
            "active": name in set(team.get("active_agents") or []),
            "capabilities": caps,
            "autonomy": {cap: resolve_autonomy(project_data, name, cap) for cap in caps},
            "ownership": (role or {}).get("owns", []),
        })
    return core.envelope(
        project,
        profiles=profiles,
        claude=claude,
        codex=codex,
        autonomy=_autonomy_config(project_data),
        capability_gates=CAPABILITY_GATES,
        runtimes=[
            {"id": "ikarus", "label": "Ikarus", "role": "orchestrator", "status": "configured"},
            {"id": "claude_code", "label": "Claude Code", "role": "frontier runtime + subagents", "status": "configured" if claude["subagent_count"] else "needs_subagents"},
            {"id": "codex", "label": "Codex", "role": "coding collaborator + app builder", "status": "configured" if codex["agents_md"]["managed"] else "needs_agents_md"},
            {"id": "ollama", "label": "Ollama Bench", "role": "local verified worker lane", "status": "local"},
        ],
    )


def save_autonomy(project: str, patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ProjectRowUpdateError("autonomy patch must be a JSON object")

    changes: dict[str, Any] = {}
    if "default" in patch:
        changes["default"] = _norm_mode(patch["default"], "manual")
    if "agents" in patch:
        try:
            changes["agents"] = dict(patch["agents"] or {})
        except (TypeError, ValueError) as exc:
            raise ProjectRowUpdateError("autonomy agents must be an object") from exc
    if "capabilities" in patch:
        try:
            changes["capabilities"] = dict(patch["capabilities"] or {})
        except (TypeError, ValueError) as exc:
            raise ProjectRowUpdateError(
                "autonomy capabilities must be an object"
            ) from exc

    def mutate(team: dict[str, Any]) -> None:
        autonomy = team.get("autonomy")
        if autonomy is None:
            autonomy = {}
            team["autonomy"] = autonomy
        elif not isinstance(autonomy, dict):
            raise ProjectRegistryUnavailable(
                "project registry row has invalid team autonomy data"
            )
        autonomy.update(changes)

    rewrite_project_team(project, mutate)
    return unified_profiles(project)
