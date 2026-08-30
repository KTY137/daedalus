# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Hierarchy graph projection for the Agent OS webapp."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import core
from .projects import load_project
from .router import load_agents

CAPABILITIES = [
    {
        "id": "web_search",
        "name": "Web Search",
        "description": "Research public information through an approved search connector.",
        "requires_secret": False,
        "risk": "external_read",
    },
    {
        "id": "github_read",
        "name": "GitHub Read",
        "description": "Read issues, pull requests, and repository metadata.",
        "requires_secret": False,
        "risk": "external_read",
    },
    {
        "id": "ollama_write",
        "name": "Ollama Write",
        "description": "Run local verified rewrite tasks through Ollama.",
        "requires_secret": False,
        "risk": "local_write",
    },
    {
        "id": "deepseek_advisory",
        "name": "DeepSeek Advisory",
        "description": "Use DeepSeek for non-sensitive read-only advice when a key is configured.",
        "requires_secret": True,
        "env_key": "DEEPSEEK_API_KEY",
        "risk": "external_advisory",
    },
    {
        "id": "claude_escalate",
        "name": "Claude Escalate",
        "description": "Escalate high-risk or frontier work to the Claude CLI.",
        "requires_secret": False,
        "risk": "trusted_frontier",
    },
]


def capabilities() -> dict[str, Any]:
    return core.envelope(None, capabilities=CAPABILITIES)


def _node(node_id: str, kind: str, label: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": kind, "label": label, "data": data}


def _edge(source: str, target: str, kind: str, **data: Any) -> dict[str, Any]:
    return {"id": f"{source}->{target}:{kind}", "source": source, "target": target, "type": kind, "data": data}


def _policy_flags(project_data: dict[str, Any]) -> dict[str, Any]:
    policy = project_data.get("policy") or {}
    return {
        "deny_count": len(policy.get("deny") or []),
        "allow_count": len(policy.get("allow") or []),
        "high_risk_paths": len(policy.get("high_risk_paths") or []),
        "high_risk_terms": len(policy.get("high_risk_terms") or []),
        "deny_content": len(policy.get("deny_content") or []),
    }


def hierarchy(project: str) -> dict[str, Any]:
    project_data = load_project(project)
    repo_root = project_data.get("repo_root")
    team = core.team_config(project)
    categories = core.get_categories(project).get("categories", [])
    agents = load_agents(repo_root)
    category_by_id = {c["id"]: c for c in categories}
    active = set(team.get("active_agents") or [a.get("name") for a in agents])
    model_assignments = team.get("model_assignments") or {}

    nodes: list[dict[str, Any]] = [
        _node(
            f"project:{project}",
            "project",
            project,
            repo_root=repo_root,
            default_lane=team.get("default_lane"),
            max_workers=team.get("max_workers"),
            policy_flags=_policy_flags(project_data),
        )
    ]
    edges: list[dict[str, Any]] = []

    for squad_name, members in (team.get("squads") or {}).items():
        squad_id = f"squad:{squad_name}"
        nodes.append(_node(squad_id, "squad", squad_name, count=len(members)))
        edges.append(_edge(f"project:{project}", squad_id, "contains"))
        for member in members:
            edges.append(_edge(squad_id, f"agent:{member}", "member"))

    for cat in categories:
        cat_id = f"category:{cat['id']}"
        nodes.append(_node(cat_id, "category", cat.get("name", cat["id"]), **cat))
        edges.append(_edge(f"project:{project}", cat_id, "category"))

    seen_models: set[str] = set()
    for agent in agents:
        name = agent.get("name", "")
        agent_id = f"agent:{name}"
        category = agent.get("category", "")
        assigned_model = model_assignments.get(name) or agent.get("model_tier", "")
        capability_ids = ["ollama_write", "claude_escalate"]
        if agent.get("external_ok"):
            capability_ids.extend(["deepseek_advisory", "web_search", "github_read"])
        nodes.append(_node(
            agent_id,
            "agent",
            agent.get("call_name") or name,
            **agent,
            active=name in active,
            assigned_model=assigned_model,
            capabilities=capability_ids,
            policy_flags={
                "external_ok": bool(agent.get("external_ok")),
                "local_only": not bool(agent.get("external_ok")),
                "category_known": category in category_by_id,
            },
        ))
        if category:
            edges.append(_edge(f"category:{category}", agent_id, "classifies"))
        for own in agent.get("owns") or []:
            path_id = f"path:{own}"
            nodes.append(_node(path_id, "path", own, path=own))
            edges.append(_edge(agent_id, path_id, "owns"))
        if assigned_model:
            model_id = f"model:{assigned_model}"
            if model_id not in seen_models:
                seen_models.add(model_id)
                nodes.append(_node(model_id, "model", assigned_model, model=assigned_model))
            edges.append(_edge(agent_id, model_id, "uses_model"))
        for cap in capability_ids:
            edges.append(_edge(agent_id, f"capability:{cap}", "can_use"))

    for cap in CAPABILITIES:
        nodes.append(_node(f"capability:{cap['id']}", "capability", cap["name"], **cap))

    health = {
        "active_agents": len(active),
        "total_agents": len(agents),
        "categories": len(categories),
        "squads": len(team.get("squads") or {}),
        "warnings": [],
    }
    return core.envelope(
        project,
        nodes=nodes,
        edges=edges,
        health=health,
        capabilities=CAPABILITIES,
        policy_flags=_policy_flags(project_data),
    )


def save_team(project: str, patch: dict[str, Any]) -> dict[str, Any]:
    from .projects import PROJECT_DIR

    path = PROJECT_DIR / f"{project}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    team = data.setdefault("team", {})
    for key in ("max_workers", "default_lane", "active_agents", "squads", "model_assignments", "semi_auto"):
        if key in patch:
            team[key] = patch[key]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return core.envelope(project, team=core.team_config(project))
