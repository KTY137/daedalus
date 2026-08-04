"""Exact inert descriptors for promotion-execution effect ownership.

The canonical registry lives in :mod:`daedalus.spine.effect_boundary`.  This
module deliberately does not import it, mutate it, or register anything at
import time.  It retains the three exact ledger rows required by the next
strangler step and materializes them only when the canonical boundary injects
its own contract and enum types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class PromotionExecutionRowDescriptor:
    entrypoint_id: str
    target: str
    surface: str
    effects: tuple[str, ...]
    guard_contracts: tuple[str, ...]
    wiring: str
    notes: str

    def __post_init__(self) -> None:
        for field_name in (
            "entrypoint_id",
            "target",
            "surface",
            "wiring",
            "notes",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty text")
        if not self.entrypoint_id.startswith("kernel.promotion_execution."):
            raise ValueError("promotion execution row has wrong identity prefix")
        if not self.target.startswith(
            "daedalus.kernel.promotion_execution:PromotionExecutionLedger."
        ):
            raise ValueError("promotion execution row has wrong target authority")
        if self.surface != "python":
            raise ValueError("promotion execution rows must use python surface")
        if self.effects != ("filesystem_write",):
            raise ValueError("promotion execution rows have one filesystem effect")
        if self.guard_contracts != ("spine.intent_ledger",):
            raise ValueError("promotion execution rows require the intent ledger")
        if self.wiring != "local_guards":
            raise ValueError(
                "promotion execution rows remain local_guards until Gate-0 "
                "EffectLease, runtime conformance and sandbox composition"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.entrypoint_id,
            "target": self.target,
            "surface": self.surface,
            "effects": list(self.effects),
            "guard_contracts": list(self.guard_contracts),
            "wiring": self.wiring,
            "notes": self.notes,
        }


PROMOTION_EXECUTION_ROW_DESCRIPTORS: tuple[
    PromotionExecutionRowDescriptor, ...
] = (
    PromotionExecutionRowDescriptor(
        entrypoint_id="kernel.promotion_execution.open",
        target=(
            "daedalus.kernel.promotion_execution:"
            "PromotionExecutionLedger.__init__"
        ),
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=("spine.intent_ledger",),
        wiring="local_guards",
        notes=(
            "Opens the canonical durable Event Store and installs the exact "
            "single-start uniqueness invariant. Inventory only: no EffectLease, "
            "runtime-conformance receipt or Docker sandbox is composed yet."
        ),
    ),
    PromotionExecutionRowDescriptor(
        entrypoint_id="kernel.promotion_execution.begin",
        target=(
            "daedalus.kernel.promotion_execution:"
            "PromotionExecutionLedger.begin"
        ),
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=("spine.intent_ledger",),
        wiring="local_guards",
        notes=(
            "Commits the exact promotion start intent before lock-file or "
            "worktree mutation. Inventory only: central runtime composition "
            "remains a later Gate-0 packet."
        ),
    ),
    PromotionExecutionRowDescriptor(
        entrypoint_id="kernel.promotion_execution.complete",
        target=(
            "daedalus.kernel.promotion_execution:"
            "PromotionExecutionLedger.complete"
        ),
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=("spine.intent_ledger",),
        wiring="local_guards",
        notes=(
            "Commits the canonical terminal receipt and report after exact "
            "manager audit assessment. Inventory only: central runtime "
            "composition remains a later Gate-0 packet."
        ),
    ),
)


def _assert_descriptor_set(
    descriptors: tuple[PromotionExecutionRowDescriptor, ...],
) -> None:
    expected_ids = (
        "kernel.promotion_execution.open",
        "kernel.promotion_execution.begin",
        "kernel.promotion_execution.complete",
    )
    if tuple(row.entrypoint_id for row in descriptors) != expected_ids:
        raise ValueError("promotion execution descriptor identities are not exact")
    if len({row.entrypoint_id for row in descriptors}) != len(descriptors):
        raise ValueError("promotion execution descriptor identities are duplicated")
    if len({row.target for row in descriptors}) != len(descriptors):
        raise ValueError("promotion execution descriptor targets are duplicated")


def materialize_promotion_execution_rows(
    *,
    entrypoint_spec: Callable[..., Any],
    surface_values: Mapping[str, Any],
    effect_values: Mapping[str, Any],
    wiring_values: Mapping[str, Any],
    descriptors: tuple[PromotionExecutionRowDescriptor, ...] = (
        PROMOTION_EXECUTION_ROW_DESCRIPTORS
    ),
) -> tuple[Any, ...]:
    """Materialize exact rows using canonical types supplied by the registry.

    Dependency injection keeps this module import-cycle free.  The function is
    pure: it returns new immutable row objects and never changes a module-level
    registry or performs an external effect.
    """
    if not callable(entrypoint_spec):
        raise TypeError("entrypoint_spec must be callable")
    if not isinstance(descriptors, tuple) or not all(
        isinstance(row, PromotionExecutionRowDescriptor) for row in descriptors
    ):
        raise TypeError("descriptors must be a typed tuple")
    _assert_descriptor_set(descriptors)

    rows: list[Any] = []
    for descriptor in descriptors:
        try:
            surface = surface_values[descriptor.surface]
            effects = tuple(effect_values[value] for value in descriptor.effects)
            wiring = wiring_values[descriptor.wiring]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                "canonical promotion execution enum mapping is incomplete"
            ) from exc
        rows.append(
            entrypoint_spec(
                id=descriptor.entrypoint_id,
                surface=surface,
                target=descriptor.target,
                effects=effects,
                guard_contracts=descriptor.guard_contracts,
                wiring=wiring,
                notes=descriptor.notes,
            )
        )
    return tuple(rows)


_assert_descriptor_set(PROMOTION_EXECUTION_ROW_DESCRIPTORS)


__all__ = [
    "PROMOTION_EXECUTION_ROW_DESCRIPTORS",
    "PromotionExecutionRowDescriptor",
    "materialize_promotion_execution_rows",
]
