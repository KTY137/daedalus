from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agents"


def load_agents() -> list[dict]:
    agents: list[dict] = []
    for path in sorted(AGENT_DIR.glob("*.json")):
        agents.append(json.loads(path.read_text(encoding="utf-8")))
    return agents


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def route_task(objective: str, paths: list[str] | None = None) -> dict:
    paths = [_norm(p) for p in (paths or [])]
    objective_l = objective.lower()
    best: tuple[int, dict] | None = None

    for agent in load_agents():
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
        return next(agent for agent in load_agents() if agent["name"] == "qa-critic")
    return best[1]
