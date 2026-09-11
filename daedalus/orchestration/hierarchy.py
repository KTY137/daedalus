"""Hierarchy graph projection for the Agent OS webapp."""
from __future__ import annotations

from typing import Any

from .. import core
from ..foundation.projects import ProjectRowUpdateError, load_project, rewrite_project_team
from ..router import load_agents

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
        # The team editor's choices come from the backend that validates them.
        # A frontend that hardcodes its own lane list will eventually offer one
        # save_team refuses, and the user finds out via a 400.
        lanes=list(core.KNOWN_LANES),
        max_workers_ceiling=MAX_WORKERS_CEILING,
    )


#: A worker ceiling, not a limit anyone asked for: it exists so a typo cannot
#: persist a fan-out that the scheduler will then honour. Raise it deliberately.
MAX_WORKERS_CEILING = 64


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ProjectRowUpdateError(message)


def _valid_max_workers(value: Any) -> int:
    # bool is an int in Python, and `True` workers is not a fan-out.
    _require(isinstance(value, int) and not isinstance(value, bool), "max_workers must be an integer")
    _require(1 <= value <= MAX_WORKERS_CEILING, f"max_workers must be between 1 and {MAX_WORKERS_CEILING}")
    return int(value)


def _valid_default_lane(value: Any) -> str:
    _require(isinstance(value, str), "default_lane must be a string")
    _require(
        value in core.KNOWN_LANES,
        f"default_lane must be one of: {', '.join(core.KNOWN_LANES)}",
    )
    return value


def _valid_name_list(value: Any, field: str) -> list[str]:
    _require(isinstance(value, list), f"{field} must be a list")
    names: list[str] = []
    for item in value:
        _require(
            isinstance(item, str) and item.strip(),
            f"{field} entries must be non-empty strings",
        )
        names.append(item.strip())
    return names


def _valid_squads(value: Any) -> dict[str, list[str]]:
    _require(isinstance(value, dict), "squads must be an object")
    return {
        _valid_key(name, "squad names"): _valid_name_list(members, f"squad '{name}'")
        for name, members in value.items()
    }


def _valid_key(name: Any, field: str) -> str:
    _require(isinstance(name, str) and name.strip(), f"{field} must be non-empty strings")
    return name.strip()


def _valid_model_assignments(value: Any) -> dict[str, str]:
    _require(isinstance(value, dict), "model_assignments must be an object")
    out: dict[str, str] = {}
    for agent, model in value.items():
        key = _valid_key(agent, "model_assignments keys")
        _require(isinstance(model, str), f"model_assignments['{key}'] must be a string")
        out[key] = model
    return out


def _valid_semi_auto(value: Any) -> dict[str, bool]:
    _require(isinstance(value, dict), "semi_auto must be an object")
    out: dict[str, bool] = {}
    for flag, on in value.items():
        key = _valid_key(flag, "semi_auto keys")
        _require(isinstance(on, bool), f"semi_auto['{key}'] must be true or false")
        out[key] = on
    return out


#: One validator per patchable field. A field with no validator is not
#: patchable, which is the same rule the old key tuple expressed -- this just
#: also says what each field has to BE.
TEAM_FIELD_VALIDATORS = {
    "max_workers": _valid_max_workers,
    "default_lane": _valid_default_lane,
    "active_agents": lambda v: _valid_name_list(v, "active_agents"),
    "squads": _valid_squads,
    "model_assignments": _valid_model_assignments,
    "semi_auto": _valid_semi_auto,
}


def save_team(project: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Patch a project's team config, validating every value on the way in.

    This used to key-filter and then write whatever arrived. That was safe
    only while nothing could reach the endpoint; the cockpit now can, and an
    unvalidated write here is a poison pill for every READ path, not a
    cosmetic problem:

    * ``core.team_config`` does ``int(team.get("max_workers", 3) or 3)``, so a
      stored ``"abc"`` raises ``ValueError`` on every subsequent read --
      dashboard, hierarchy, routing and build all fail for that project, and
      nothing in the UI can undo it because the undo path reads first.
    * ``active_agents`` is read as ``[str(a) for a in ...]``, so a stored
      string ``"claude"`` silently becomes the six agents ``c, l, a, u, d, e``.
    * ``default_lane`` reaches ``core.routing_summary``, which treats anything
      that is not ``local_only`` as a configured lane to honour.

    Rejections raise ``ProjectRowUpdateError``, which ``web_api`` already maps
    to HTTP 400 with the message, so the caller is told which field and why.
    """
    if not isinstance(patch, dict):
        raise ProjectRowUpdateError("team patch must be a JSON object")
    # Unknown keys are IGNORED, not rejected: that is the existing contract and
    # the reason a patch cannot escape the team subtree (see
    # test_project_row_rewrite.py, which patches `name`, `repo_root`, `policy`
    # and asserts the row is untouched). They are reported in the envelope
    # rather than dropped in silence -- an ignored field is indistinguishable
    # from a saved one from the caller's side, and this repository's standing
    # order is to say what was withheld.
    ignored = sorted(set(patch) - set(TEAM_FIELD_VALIDATORS))
    changes = {
        key: TEAM_FIELD_VALIDATORS[key](patch[key])
        for key in TEAM_FIELD_VALIDATORS
        if key in patch
    }

    def mutate(team: dict[str, Any]) -> None:
        team.update(changes)

    rewrite_project_team(project, mutate)
    return core.envelope(
        project, team=core.team_config(project), ignored_fields=ignored
    )
