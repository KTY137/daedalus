"""Install the promotion execution rows into the canonical effect registry.

This is a temporary strangler adapter while the large legacy registry remains in
``daedalus.spine.effect_boundary``.  It mutates only that module's immutable
registry projections during package initialization, before callers can import
them.  No effect is executed and no row is upgraded to ``central`` here.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any


def _promotion_rows(boundary: Any) -> tuple[Any, ...]:
    return (
        boundary.EntrypointSpec(
            id="kernel.promotion_execution.begin",
            surface=boundary.Surface.PYTHON,
            target=(
                "daedalus.kernel.promotion_execution:"
                "PromotionExecutionLedger.begin"
            ),
            effects=(boundary.Effect.FILESYSTEM_WRITE,),
            guard_contracts=("spine.intent_ledger",),
            wiring=boundary.Wiring.LOCAL_GUARDS,
            anchors=(
                boundary.GuardAnchor(
                    "daedalus.kernel.promotion_execution:"
                    "PromotionExecutionLedger.begin",
                    "record_intent",
                ),
            ),
            notes=(
                "Persists the exact promotion execution start in the canonical "
                "Event Store before repository mutation."
            ),
            migration=(
                "Compose the persisted EffectLease, current runtime conformance "
                "and Docker sandbox before upgrading this row to central."
            ),
        ),
        boundary.EntrypointSpec(
            id="kernel.promotion_execution.complete",
            surface=boundary.Surface.PYTHON,
            target=(
                "daedalus.kernel.promotion_execution:"
                "PromotionExecutionLedger.complete"
            ),
            effects=(boundary.Effect.FILESYSTEM_WRITE,),
            guard_contracts=("spine.intent_ledger",),
            wiring=boundary.Wiring.LOCAL_GUARDS,
            anchors=(
                boundary.GuardAnchor(
                    "daedalus.kernel.promotion_execution:"
                    "PromotionExecutionLedger.complete",
                    "mark_completed",
                ),
            ),
            notes=(
                "Persists one terminal promotion execution receipt in the same "
                "canonical Event Store."
            ),
            migration=(
                "Compose the persisted EffectLease, current runtime conformance "
                "and Docker sandbox before upgrading this row to central."
            ),
        ),
    )


def install_promotion_effect_rows(boundary: Any) -> None:
    """Install exactly two local-guard rows and refresh registry defaults."""
    required = _promotion_rows(boundary)
    existing = {row.id: row for row in boundary.ENTRYPOINTS}
    if len(existing) != len(boundary.ENTRYPOINTS):
        raise RuntimeError("canonical effect registry contains duplicate ids")

    present = [existing.get(row.id) for row in required]
    if any(row is not None for row in present):
        if tuple(present) != required:
            raise RuntimeError("promotion effect rows are partially or incorrectly installed")
        return

    boundary.ENTRYPOINTS = (*boundary.ENTRYPOINTS, *required)
    boundary.REGISTRY_BY_ID = MappingProxyType(
        {row.id: row for row in boundary.ENTRYPOINTS}
    )

    # The legacy module captured its immutable registry projections in function
    # defaults. Refresh those exact defaults once, during package initialization,
    # so every normal import observes the same canonical rows.
    boundary.registry_sha256.__defaults__ = (boundary.ENTRYPOINTS,)
    boundary.begin_effect.__kwdefaults__ = {
        **(boundary.begin_effect.__kwdefaults__ or {}),
        "registry": boundary.REGISTRY_BY_ID,
    }
    boundary.check_conformance.__kwdefaults__ = {
        **(boundary.check_conformance.__kwdefaults__ or {}),
        "registry": boundary.ENTRYPOINTS,
    }


__all__ = ["install_promotion_effect_rows"]
