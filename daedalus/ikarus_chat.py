"""Ikarus network-designer chat for the Agent OS.

This is intentionally deterministic for v1: it turns an operator message into
a reviewable agent-network draft, and applies that draft only when explicitly
requested by the UI/API caller.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import agents_registry, control_plane, core, hierarchy
from .projects import resolve_repo_root


BLUEPRINTS: list[dict[str, Any]] = [
    {
        "name": "network-architect",
        "call_name": "Ikarus",
        "model_tier": "opus",
        "external_ok": False,
        "category": "implementation",
        "owns": [".agentenv/", "projects/"],
        "triggers": ["agent network", "orchestration", "routing", "squad", "capability", "hierarchy"],
        "must_read": ["AGENTS.md", "CLAUDE.md"],
    },
    {
        "name": "frontend-studio",
        "call_name": "Vega",
        "model_tier": "sonnet",
        "external_ok": False,
        "category": "design",
        "owns": ["apps/web/", "vscode-agent-env/"],
        "triggers": ["ui", "ux", "react", "graph", "dashboard", "webapp", "visual"],
        "must_read": ["vscode-agent-env/DESIGN.md"],
    },
    {
        "name": "api-steward",
        "call_name": "Atlas",
        "model_tier": "sonnet",
        "external_ok": False,
        "category": "implementation",
        "owns": ["daedalus/web_api.py", "daedalus/hierarchy.py", "daedalus/core.py"],
        "triggers": ["api", "backend", "endpoint", "contract", "server", "schema"],
        "must_read": ["docs/COMMS_PROTOCOL.md"],
    },
    {
        "name": "qa-sentinel",
        "call_name": "Talos",
        "model_tier": "opus",
        "external_ok": False,
        "category": "tests",
        "owns": ["tests/"],
        "triggers": ["test", "regression", "playwright", "smoke", "contract", "risk"],
        "must_read": ["docs/GO_LIVE.md"],
    },
    {
        "name": "memory-scribe",
        "call_name": "Mneme",
        "model_tier": "haiku",
        "external_ok": False,
        "category": "docs",
        "owns": ["docs/", "memory/", "README.md"],
        "triggers": ["docs", "memory", "runbook", "decision log", "handoff", "changelog"],
        "must_read": ["docs/ARCHITECTURE.md"],
    },
    {
        "name": "research-scout",
        "call_name": "Lyra",
        "model_tier": "sonnet",
        "external_ok": True,
        "category": "research",
        "owns": ["docs/research", "docs/"],
        "triggers": ["research", "source", "api docs", "benchmark", "market", "library"],
        "must_read": ["docs/PROVIDERS_RESEARCH.md"],
    },
]


def _select_blueprints(message: str) -> list[dict[str, Any]]:
    text = message.lower()
    selected: list[dict[str, Any]] = [BLUEPRINTS[0]]
    rules = [
        ("frontend-studio", ("ui", "ux", "frontend", "design", "webapp", "graph", "visual")),
        ("api-steward", ("api", "backend", "server", "endpoint", "env", "secret")),
        ("qa-sentinel", ("test", "qa", "quality", "verify", "regression", "playwright")),
        ("memory-scribe", ("docs", "memory", "handoff", "bookkeeping", "changelog")),
        ("research-scout", ("research", "web", "github", "source", "api docs", "connector")),
    ]
    by_name = {b["name"]: b for b in BLUEPRINTS}
    for name, needles in rules:
        if any(n in text for n in needles):
            selected.append(by_name[name])
    if len(selected) == 1 or any(word in text for word in ("full", "complete", "network", "hierarchy", "all", "alles")):
        selected = BLUEPRINTS[:]
    return list({b["name"]: b for b in selected}.values())


def _team_patch(roles: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    squads = dict(current.get("squads") or {})
    squads.setdefault("Orchestration", [])
    squads.setdefault("Product UI", [])
    squads.setdefault("Backend API", [])
    squads.setdefault("Quality", [])
    squads.setdefault("Knowledge", [])
    squads.setdefault("Research", [])
    mapping = {
        "network-architect": "Orchestration",
        "frontend-studio": "Product UI",
        "api-steward": "Backend API",
        "qa-sentinel": "Quality",
        "memory-scribe": "Knowledge",
        "research-scout": "Research",
    }
    for role in roles:
        squad = mapping.get(role["name"], "Orchestration")
        members = list(dict.fromkeys([*squads.get(squad, []), role["name"]]))
        squads[squad] = members
    active = list(dict.fromkeys([*(current.get("active_agents") or []), *(r["name"] for r in roles)]))
    assignments = dict(current.get("model_assignments") or {})
    for role in roles:
        assignments.setdefault(role["name"], "qwen2.5-coder:7b")
    return {
        "active_agents": active,
        "squads": squads,
        "model_assignments": assignments,
        "max_workers": max(int(current.get("max_workers") or 3), min(8, len(active))),
        "autonomy": {
            **(current.get("autonomy") or {}),
            "default": (current.get("autonomy") or {}).get("default", "manual"),
            "agents": {
                **((current.get("autonomy") or {}).get("agents") or {}),
                **{role["name"]: "semi_auto" if role["category"] in ("docs", "tests", "research") else "manual" for role in roles},
            },
        },
    }


def _subagent_for(role: dict[str, Any]) -> dict[str, Any]:
    tools = "Read, Grep, Glob"
    if role["category"] in ("docs", "tests", "research"):
        tools = "Read, Grep, Glob, Bash"
    if role.get("external_ok"):
        tools = f"{tools}, mcp__*"
    return {
        "name": role["name"],
        "description": f"{role['call_name']} handles {role['category']} work for this project through the Daedalus control plane.",
        "model": "inherit",
        "tools": tools,
        "body": (
            f"You are {role['call_name']} / {role['name']}.\n\n"
            "Work as a specialized Claude Code subagent coordinated by Daedalus.\n"
            "Respect project policy, avoid secrets, and return concise handoffs.\n"
            f"Primary ownership: {', '.join(role.get('owns') or ['project-specific tasks'])}.\n"
        ),
    }


def _subagent_markdown(spec: dict[str, Any]) -> str:
    return (
        "---\n"
        f"name: {spec['name']}\n"
        f"description: {spec['description']}\n"
        f"model: {spec['model']}\n"
        f"tools: {spec['tools']}\n"
        "---\n\n"
        f"{spec['body']}"
    )


def draft(project: str, message: str) -> dict[str, Any]:
    team = core.team_config(project)
    roles = _select_blueprints(message)
    patch = _team_patch(roles, team)
    subagents = [_subagent_for(role) for role in roles]
    names = ", ".join(r["call_name"] for r in roles)
    assistant = (
        f"I would draft {len(roles)} unified agent profiles: {names}. "
        "Each profile includes a Daedalus role, a Claude Code subagent, squad membership, and an autonomy default. "
        "Risky capabilities stay manual unless you explicitly relax them."
    )
    return core.envelope(project, assistant=assistant, draft={"roles": roles, "subagents": subagents, "team_patch": patch})


def chat(project: str, message: str, *, apply: bool = False) -> dict[str, Any]:
    payload = draft(project, message)
    if not apply:
        return payload

    repo_root = resolve_repo_root(None, project)
    applied: list[str] = []
    for role in payload["draft"]["roles"]:
        try:
            agents_registry.create_role(role, repo_root, overwrite=False)
        except FileExistsError:
            agents_registry.update_role(role["name"], role, repo_root)
        applied.append(role["name"])
    subagent_dir = Path(repo_root) / ".claude" / "agents"
    subagent_dir.mkdir(parents=True, exist_ok=True)
    for subagent in payload["draft"]["subagents"]:
        (subagent_dir / f"{subagent['name']}.md").write_text(_subagent_markdown(subagent), encoding="utf-8")
    hierarchy.save_team(project, payload["draft"]["team_patch"])
    return {
        **payload,
        "applied": applied,
        "control_plane": control_plane.unified_profiles(project),
        "assistant": payload["assistant"] + " Applied the confirmed draft to Daedalus and Claude Code config.",
    }
