"""Inert registry descriptors for recovery-decision persistence effects.

The canonical effect registry remains in :mod:`daedalus.spine.effect_boundary`.
This module neither imports nor mutates that registry.  It defines the exact two
filesystem-write surfaces introduced by the one-use recovery-consumption ledger
and materializes them only from canonical types supplied by the registry owner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


_OPEN_ID = "kernel.promotion_recovery_consumption.open"
_CONSUME_ID = "kernel.promotion_recovery_consumption.consume"
_TARGET_PREFIX = (
    "daedalus.kernel.promotion_recovery_consumption:"
    "PromotionRecoveryConsumptionLedger."
)
_STORE_GUARD = "promotion.recovery_consumption_store"
_DECISION_GUARD = "promotion.owner_recovery_decision"


@dataclass(frozen=True)
class PromotionRecoveryConsumptionRowDescriptor:
    entrypoint_id: str
    target: str
    surface: str
    effects: tuple[str, ...]
    guard_contracts: tuple[str, ...]
    wiring: str
    anchors: tuple[tuple[str, str], ...]
    notes: str

    def __post_init__(self) -> None:
        for name in (
            "entrypoint_id",
            "target",
            "surface",
            "wiring",
            "notes",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text")
        if self.entrypoint_id not in {_OPEN_ID, _CONSUME_ID}:
            raise ValueError("recovery-consumption row has an unknown identity")
        expected_target = (
            _TARGET_PREFIX
            + ("__init__" if self.entrypoint_id == _OPEN_ID else "consume")
        )
        if self.target != expected_target:
            raise ValueError("recovery-consumption row has the wrong target")
        if self.surface != "python":
            raise ValueError("recovery-consumption rows must use python surface")
        if self.effects != ("filesystem_write",):
            raise ValueError(
                "recovery-consumption rows declare one filesystem-write effect"
            )
        expected_guards = (
            (_STORE_GUARD,)
            if self.entrypoint_id == _OPEN_ID
            else (_DECISION_GUARD, _STORE_GUARD)
        )
        if self.guard_contracts != expected_guards:
            raise ValueError(
                "recovery-consumption row has the wrong exact guard contracts"
            )
        if self.wiring != "local_guards":
            raise ValueError(
                "recovery-consumption rows remain local_guards until the "
                "EffectLease, runtime-conformance and sandbox packet"
            )
        if not isinstance(self.anchors, tuple) or not self.anchors:
            raise ValueError("recovery-consumption row requires exact anchors")
        for anchor in self.anchors:
            if (
                not isinstance(anchor, tuple)
                or len(anchor) != 2
                or not all(isinstance(value, str) and value for value in anchor)
            ):
                raise ValueError("recovery-consumption anchors must be text pairs")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.entrypoint_id,
            "target": self.target,
            "surface": self.surface,
            "effects": list(self.effects),
            "guard_contracts": list(self.guard_contracts),
            "wiring": self.wiring,
            "anchors": [
                {"target": target, "call": call}
                for target, call in self.anchors
            ],
            "notes": self.notes,
        }


PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS: tuple[
    PromotionRecoveryConsumptionRowDescriptor, ...
] = (
    PromotionRecoveryConsumptionRowDescriptor(
        entrypoint_id=_OPEN_ID,
        target=_TARGET_PREFIX + "__init__",
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=(_STORE_GUARD,),
        wiring="local_guards",
        anchors=(
            (_TARGET_PREFIX + "__init__", "_initialize"),
            (_TARGET_PREFIX + "_initialize", "_connect_writer"),
        ),
        notes=(
            "Creates or opens the durable one-use recovery-consumption store. "
            "The row is inventory-visible but not centrally authorized yet."
        ),
    ),
    PromotionRecoveryConsumptionRowDescriptor(
        entrypoint_id=_CONSUME_ID,
        target=_TARGET_PREFIX + "consume",
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=(_DECISION_GUARD, _STORE_GUARD),
        wiring="local_guards",
        anchors=(
            (_TARGET_PREFIX + "consume", "verify_promotion_recovery_decision"),
            (_TARGET_PREFIX + "consume", "_connect_writer"),
        ),
        notes=(
            "Authenticates current owner recovery authority twice and commits "
            "one canonical one-use receipt. No cancellation writer is included."
        ),
    ),
)


def _assert_exact_descriptors(
    descriptors: tuple[PromotionRecoveryConsumptionRowDescriptor, ...],
) -> None:
    expected = (_OPEN_ID, _CONSUME_ID)
    identities = tuple(row.entrypoint_id for row in descriptors)
    if identities != expected:
        raise ValueError(
            "recovery-consumption descriptor identities/order are not exact"
        )
    if len({row.target for row in descriptors}) != len(descriptors):
        raise ValueError("recovery-consumption descriptor targets are duplicated")
    if len({anchor for row in descriptors for anchor in row.anchors}) != sum(
        len(row.anchors) for row in descriptors
    ):
        raise ValueError("recovery-consumption descriptor anchors are duplicated")


def materialize_promotion_recovery_consumption_rows(
    *,
    entrypoint_spec: Callable[..., Any],
    guard_anchor: Callable[..., Any],
    surface_values: Mapping[str, Any],
    effect_values: Mapping[str, Any],
    wiring_values: Mapping[str, Any],
    descriptors: tuple[PromotionRecoveryConsumptionRowDescriptor, ...] = (
        PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS
    ),
) -> tuple[Any, ...]:
    """Return canonical row objects without changing any registry."""

    if not callable(entrypoint_spec):
        raise TypeError("entrypoint_spec must be callable")
    if not callable(guard_anchor):
        raise TypeError("guard_anchor must be callable")
    if not isinstance(descriptors, tuple) or not all(
        isinstance(row, PromotionRecoveryConsumptionRowDescriptor)
        for row in descriptors
    ):
        raise TypeError("descriptors must be an exact typed tuple")
    _assert_exact_descriptors(descriptors)

    rows: list[Any] = []
    for descriptor in descriptors:
        try:
            surface = surface_values[descriptor.surface]
            effects = tuple(
                effect_values[value] for value in descriptor.effects
            )
            wiring = wiring_values[descriptor.wiring]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "canonical recovery-consumption enum mapping is incomplete"
            ) from exc
        anchors = tuple(
            guard_anchor(target=target, call=call)
            for target, call in descriptor.anchors
        )
        rows.append(
            entrypoint_spec(
                id=descriptor.entrypoint_id,
                surface=surface,
                target=descriptor.target,
                effects=effects,
                guard_contracts=descriptor.guard_contracts,
                wiring=wiring,
                anchors=anchors,
                notes=descriptor.notes,
            )
        )
    return tuple(rows)


_assert_exact_descriptors(PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS)


__all__ = [
    "PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS",
    "PromotionRecoveryConsumptionRowDescriptor",
    "materialize_promotion_recovery_consumption_rows",
]
