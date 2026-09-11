"""Compatibility facade for the runtime-owned provider persona catalogue."""

from ..runtimes.providers.personas import (
    LEGACY_PERSONAS_PATH as _REGISTRY_PATH,
    _registry,
    culture,
    persona_for,
    roster,
)

__all__ = ["culture", "persona_for", "roster"]
