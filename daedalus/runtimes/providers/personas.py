"""Runtime-owned provider persona catalogue."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from daedalus.resources import read_builtin_text


LEGACY_PERSONAS_PATH = (
    Path(__file__).resolve().parents[2] / "providers" / "personas.json"
)


@lru_cache(maxsize=1)
def _registry() -> dict:
    return json.loads(
        read_builtin_text(
            "catalogue/providers/personas.json",
            legacy=LEGACY_PERSONAS_PATH,
        )
    )


def persona_for(provider: str, agent_name: str | None) -> str:
    """Return the shadow persona's call-name for (provider, role)."""
    prov = _registry().get(provider, {})
    by_role = prov.get("by_role", {})
    return by_role.get(agent_name or "", prov.get("default", provider))


def culture(provider: str) -> str:
    return _registry().get(provider, {}).get("culture", "")


def roster(provider: str) -> list[str]:
    """All named workers on a lane: the per-role shadows plus any extra pool."""
    prov = _registry().get(provider, {})
    names = list(prov.get("by_role", {}).values()) + list(prov.get("pool", []))
    return list(dict.fromkeys(names))


__all__ = ["culture", "persona_for", "roster"]
