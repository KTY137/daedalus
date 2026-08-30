# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agents"
TEMPLATE_AGENT_DIR = ROOT / "templates" / "agents"


def _agent_dir_for(repo_root: str | None) -> Path:
    """Resolve which directory of agent-role JSON files to load.

    Back-compat: ``repo_root=None`` -> the built-in ``agents/`` dir (current
    behavior). With a ``repo_root``: prefer that repo's own
    ``<repo_root>/.agentenv/agents/`` overrides if present, else the generic
    ``templates/agents/`` defaults, else fall back to the built-in ``agents/``.
    """
    if repo_root is not None:
        repo_agents = Path(repo_root) / ".agentenv" / "agents"
        if repo_agents.is_dir() and any(repo_agents.glob("*.json")):
            return repo_agents
        if TEMPLATE_AGENT_DIR.is_dir() and any(TEMPLATE_AGENT_DIR.glob("*.json")):
            return TEMPLATE_AGENT_DIR
    return AGENT_DIR


# Non-role files that may share an agent-role directory (e.g. the
# role-category taxonomy's global seed lives at agents/categories.json).
_NON_ROLE_FILES = {"categories.json"}


def load_agents(repo_root: str | None = None, active_agents: list[str] | None = None) -> list[dict]:
    active = set(active_agents or [])
    agents: list[dict] = []
    for path in sorted(_agent_dir_for(repo_root).glob("*.json")):
        if path.name in _NON_ROLE_FILES:
            continue
        agent = json.loads(path.read_text(encoding="utf-8"))
        if active and agent.get("name") not in active:
            continue
        agents.append(agent)
    return agents


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def route_task(objective: str, paths: list[str] | None = None,
               repo_root: str | None = None,
               active_agents: list[str] | None = None) -> dict:
    paths = [_norm(p) for p in (paths or [])]
    objective_l = objective.lower()
    best: tuple[int, dict] | None = None

    agents = load_agents(repo_root, active_agents)
    if not agents:
        raise RuntimeError("no active agents configured")
    for agent in agents:
        score = 0
        for owned in agent.get("owns", []):
            owned_l = owned.lower()
            if any(owned_l in p.lower() for p in paths):
                score += 5
        for trigger in agent.get("triggers", []):
            if trigger.lower() in objective_l:
                score += 2
        if best is None or score > best[0]:
            best = (score, agent)

    if best is None:
        raise RuntimeError("no agents configured")
    if best[0] == 0:
        return next((agent for agent in agents if agent["name"] == "qa-critic"), best[1])
    return best[1]
