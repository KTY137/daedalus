# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Persona names for the free-model lanes.

Each Claude specialist keeps its name on the trusted Claude lane, but gets a
named *shadow* when the same role runs on a cheaper backend: a Chinese name on
DeepSeek (external) and a Mexican/Italian name on local Ollama. Purely cosmetic
identity so reports and the architecture map read consistently.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_REGISTRY_PATH = Path(__file__).with_name("personas.json")


@lru_cache(maxsize=1)
def _registry() -> dict:
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


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
