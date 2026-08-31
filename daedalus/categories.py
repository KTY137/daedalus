"""Role-category taxonomy — strictly additive metadata layer.

Categories group agent roles for the UI (icon/color/lane/tier presets) and
tag routed tasks so the bus/reports carry a category. This module NEVER
makes a routing decision itself: ``provider_router``'s risk/sensitivity
lane logic stays authoritative. ``preset_for`` only returns a *suggested*
{lane, tier} for a role to pre-fill a form or a badge — nothing here can
override or bypass the fail-closed lane gate in ``core.process_bridge_payload``.

Storage mirrors ``agents_registry.py``:
  - ``agents/categories.json``            -- global, shipped seed (a JSON list).
  - ``<repo_root>/.agentenv/categories.json`` -- per-repo override, written by
    ``update()``. Never mutates the shipped global file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .agents_registry import MODEL_TIERS
from .resources import read_builtin_text
from .router import ROOT, load_agents

CATEGORIES_PATH = ROOT / "agents" / "categories.json"
LANES = ("local_only", "local", "auto", "claude", "codex")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _write_dir_for(repo_root: str | None) -> Path:
    """Where an edited/new category is written (never the shipped global file)."""
    if repo_root:
        return Path(repo_root) / ".agentenv"
    raise ValueError("repo_root is required; packaged category defaults are read-only")


def _write_path_for(repo_root: str | None) -> Path:
    return _write_dir_for(repo_root) / "categories.json"


def _read_categories_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [c for c in data if isinstance(c, dict) and c.get("id")] if isinstance(data, list) else []


def validate(cat: dict[str, Any]) -> list[str]:
    """Fail-closed validation. Returns a list of human-readable errors ([] = ok)."""
    errors: list[str] = []
    cid = cat.get("id")
    if not isinstance(cid, str) or not _ID_RE.match(cid or ""):
        errors.append("id must be a lowercase slug (a-z, 0-9, '-'), 2-41 chars")
    if not isinstance(cat.get("name"), str) or not cat.get("name"):
        errors.append("name must be a non-empty string")
    if not isinstance(cat.get("icon"), str) or not cat.get("icon"):
        errors.append("icon must be a non-empty string (emoji)")
    if not isinstance(cat.get("color"), str) or not _COLOR_RE.match(cat.get("color") or ""):
        errors.append("color must be a hex string like #RRGGBB")
    if cat.get("lane") not in LANES:
        errors.append(f"lane must be one of {', '.join(LANES)}")
    if cat.get("tier") not in MODEL_TIERS:
        errors.append(f"tier must be one of {', '.join(MODEL_TIERS)}")
    triggers = cat.get("triggers", [])
    if not (isinstance(triggers, list) and all(isinstance(x, str) for x in triggers)):
        errors.append("triggers must be a list of strings")
    return errors


def normalize(cat: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults so a partial spec becomes a complete, stably-ordered category."""
    return {
        "id": cat["id"],
        "name": cat.get("name", cat["id"]),
        "icon": cat.get("icon", ""),
        "color": cat.get("color", "#495057"),
        "lane": cat.get("lane", "auto"),
        "tier": cat.get("tier", "sonnet"),
        "triggers": list(cat.get("triggers", [])),
    }


def load(repo_root: str | None = None) -> list[dict[str, Any]]:
    """Global ``agents/categories.json`` merged with a per-repo
    ``.agentenv/categories.json`` override (matched by id; repo fields win)."""
    try:
        seed = json.loads(
            read_builtin_text(
                "agents/categories.json", legacy=CATEGORIES_PATH
            )
        )
    except (OSError, json.JSONDecodeError):
        seed = []
    builtins = (
        [c for c in seed if isinstance(c, dict) and c.get("id")]
        if isinstance(seed, list)
        else []
    )
    by_id: dict[str, dict[str, Any]] = {c["id"]: c for c in builtins}
    if repo_root:
        for c in _read_categories_file(Path(repo_root) / ".agentenv" / "categories.json"):
            by_id[c["id"]] = {**by_id.get(c["id"], {}), **c}
    return list(by_id.values())


def get(cat_id: str, repo_root: str | None = None) -> dict[str, Any] | None:
    return next((c for c in load(repo_root) if c.get("id") == cat_id), None)


def update(cat_id: str, patch: dict[str, Any], repo_root: str | None = None) -> Path:
    """Merge ``patch`` over the current category and write the per-repo
    override. Packaged defaults are read-only, so ``repo_root`` is required.
    Raises ``KeyError`` if the category doesn't exist anywhere and
    ``ValueError`` for an invalid result or missing project root."""
    current = get(cat_id, repo_root)
    if current is None:
        raise KeyError(f"unknown category '{cat_id}'")
    merged = {**current, **patch, "id": cat_id}
    errors = validate(merged)
    if errors:
        raise ValueError("; ".join(errors))
    merged = normalize(merged)

    path = _write_path_for(repo_root)
    existing = _read_categories_file(path)
    by_id = {c["id"]: c for c in existing}
    by_id[cat_id] = merged
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(by_id.values()), indent=2), encoding="utf-8")
    return path


def preset_for(agent: dict[str, Any], repo_root: str | None = None) -> dict[str, str]:
    """Suggested {lane, tier} for an agent role, from its ``category`` field.
    This is a UI/default-fill hint only — it never bypasses the authoritative
    lane gate in ``provider_router``/``core.process_bridge_payload``."""
    cat_id = agent.get("category")
    if cat_id:
        cat = get(cat_id, repo_root)
        if cat:
            return {"lane": cat["lane"], "tier": cat["tier"]}
    return {"lane": "auto", "tier": agent.get("model_tier", "sonnet")}


def get_categories_joined(repo_root: str | None = None, active_agents: list[str] | None = None) -> list[dict[str, Any]]:
    """Categories joined with the agent roles tagged into them (for
    ``core.get_categories``)."""
    agents = load_agents(repo_root, active_agents)
    rows = []
    for cat in load(repo_root):
        members = [a for a in agents if a.get("category") == cat["id"]]
        rows.append({
            **cat,
            "agents": [
                {
                    "name": a.get("name"),
                    "call_name": a.get("call_name", ""),
                    "model_tier": a.get("model_tier", ""),
                    "external_ok": bool(a.get("external_ok", False)),
                }
                for a in members
            ],
            "count": len(members),
        })
    return rows
