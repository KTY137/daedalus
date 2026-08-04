"""Install promotion-execution rows into the canonical effect registry.

This temporary strangler keeps the large legacy registry in
``daedalus.spine.effect_boundary`` authoritative. It updates only that module's
immutable registry projections during package initialization, before callers
can observe them. No effect is executed and no row is upgraded to ``central``.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any


def _promotion_rows(boundary: Any) -> tuple[Any, ...]:
    common = {
        "surface": boundary.Surface.PYTHON,
        "effects": (boundary.Effect.FILESYSTEM_WRITE,),
        "guard_contracts": ("spine.intent_ledger",),
        "wiring": boundary.Wiring.LOCAL_GUARDS,
    }
    return (
        boundary.EntrypointSpec(
            id="kernel.promotion_execution.open",
            target=(
                "daedalus.kernel.promotion_execution:"
                "PromotionExecutionLedger.__init__"
            ),
            anchors=(
                boundary.GuardAnchor(
                    "daedalus.kernel.promotion_execution:"
                    "PromotionExecutionLedger.__init__",
                    "open_gate0_spine_writer",
                ),
                boundary.GuardAnchor(
                    "daedalus.kernel.promotion_execution:"
                    "PromotionExecutionLedger.__init__",
                    "_install_single_start_invariant",
                ),
            ),
            notes=(
                "Opens the canonical durable Event Store and installs the unique "
                "promotion-start invariant."
            ),
            migration=(
                "Compose EffectLease, runtime conformance and Docker sandbox "
                "authority before upgrading this row to central."
            ),
            **common,
        ),
        boundary.EntrypointSpec(
            id="kernel.promotion_execution.begin",
            target=(
                "daedalus.kernel.promotion_execution:"
                "PromotionExecutionLedger.begin"
            ),
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
                "Compose EffectLease, runtime conformance and Docker sandbox "
                "authority before upgrading this row to central."
            ),
            **common,
        ),
        boundary.EntrypointSpec(
            id="kernel.promotion_execution.complete",
            target=(
                "daedalus.kernel.promotion_execution:"
                "PromotionExecutionLedger.complete"
            ),
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
                "Compose EffectLease, runtime conformance and Docker sandbox "
                "authority before upgrading this row to central."
            ),
            **common,
        ),
    )


def install_promotion_effect_rows(boundary: Any) -> None:
    """Install exactly three local-guard rows and refresh registry defaults."""
    required = _promotion_rows(boundary)
    existing = {row.id: row for row in boundary.ENTRYPOINTS}
    if len(existing) != len(boundary.ENTRYPOINTS):
        raise RuntimeError("canonical effect registry contains duplicate ids")

    present = [existing.get(row.id) for row in required]
    if any(row is not None for row in present):
        if tuple(present) != required:
            raise RuntimeError(
                "promotion effect rows are partially or incorrectly installed"
            )
        return

    boundary.ENTRYPOINTS = (*boundary.ENTRYPOINTS, *required)
    boundary.REGISTRY_BY_ID = MappingProxyType(
        {row.id: row for row in boundary.ENTRYPOINTS}
    )
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
