"""Machine-readable inventory delta for promotion-recovery consumption writes.

This module is deliberately preparatory.  It describes the exact canonical
registry rows and scanner hooks required for the new durable recovery-decision
ledger, but it does not mutate ``effect_boundary.ENTRYPOINTS`` at import time.
That keeps the integration batch reviewable and makes the remaining unregistered
production paths explicit instead of silently pretending they are guarded.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping

from daedalus.spine.envelope import canonical_sha


@dataclass(frozen=True, slots=True)
class ProposedGuardContract:
    id: str
    implemented: bool
    evidence_target: str


@dataclass(frozen=True, slots=True)
class ProposedEntrypoint:
    id: str
    target: str
    surface: str
    effects: tuple[str, ...]
    guard_contracts: tuple[str, ...]
    wiring: str
    anchors: tuple[str, ...]
    migration: str


@dataclass(frozen=True, slots=True)
class PromotionRecoveryConsumptionInventoryDelta:
    schema: str
    guard_contracts: tuple[ProposedGuardContract, ...]
    entrypoints: tuple[ProposedEntrypoint, ...]
    scanner_module: str
    scanner_class: str
    scanner_methods: tuple[str, ...]
    canonical_registry_integrated: bool
    closed: bool
    blockers: tuple[str, ...]
    delta_sha256: str

    def payload_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "guard_contracts": [asdict(row) for row in self.guard_contracts],
            "entrypoints": [asdict(row) for row in self.entrypoints],
            "scanner_module": self.scanner_module,
            "scanner_class": self.scanner_class,
            "scanner_methods": list(self.scanner_methods),
            "canonical_registry_integrated": self.canonical_registry_integrated,
            "closed": self.closed,
            "blockers": list(self.blockers),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload_dict(),
            "delta_sha256": self.delta_sha256,
        }


GUARD_CONTRACT_IMPLEMENTED: Mapping[str, bool] = MappingProxyType(
    {"promotion.owner_recovery_decision": True}
)

GUARD_CONTRACTS: tuple[ProposedGuardContract, ...] = (
    ProposedGuardContract(
        id="promotion.owner_recovery_decision",
        implemented=True,
        evidence_target=(
            "daedalus.kernel.promotion_recovery_decision:"
            "verify_promotion_recovery_decision"
        ),
    ),
)

ENTRYPOINTS: tuple[ProposedEntrypoint, ...] = (
    ProposedEntrypoint(
        id="kernel.promotion_recovery_consumption.initialize",
        target=(
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger.__init__"
        ),
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=(),
        wiring="unguarded",
        anchors=("_initialize", "_connect_writer"),
        migration=(
            "Split schema creation from object construction and require a persisted "
            "Effect Lease before explicit database initialization."
        ),
    ),
    ProposedEntrypoint(
        id="kernel.promotion_recovery_consumption.consume",
        target=(
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger.consume"
        ),
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=("promotion.owner_recovery_decision",),
        wiring="local_guards",
        anchors=("verify_promotion_recovery_decision", "_connect_writer"),
        migration=(
            "Require the exact persisted Effect Lease and consume the recovery "
            "decision only inside the canonical effect-start lifecycle."
        ),
    ),
)

SCANNER_MODULE = "daedalus.kernel.promotion_recovery_consumption"
SCANNER_CLASS = "PromotionRecoveryConsumptionLedger"
SCANNER_METHODS = ("__init__", "consume")

BLOCKERS = (
    "canonical-effect-boundary-guard-contract-not-yet-integrated",
    "canonical-effect-boundary-entrypoint-rows-not-yet-integrated",
    "static-effect-scanner-does-not-yet-discover-recovery-consumption-writes",
    "constructor-performs-unguarded-schema-initialization",
    "consume-is-locally-owner-guarded-but-not-effect-lease-central",
)


def _build_delta() -> PromotionRecoveryConsumptionInventoryDelta:
    body = {
        "schema": "daedalus-promotion-recovery-consumption-inventory-delta/1",
        "guard_contracts": [asdict(row) for row in GUARD_CONTRACTS],
        "entrypoints": [asdict(row) for row in ENTRYPOINTS],
        "scanner_module": SCANNER_MODULE,
        "scanner_class": SCANNER_CLASS,
        "scanner_methods": list(SCANNER_METHODS),
        "canonical_registry_integrated": False,
        "closed": False,
        "blockers": list(BLOCKERS),
    }
    return PromotionRecoveryConsumptionInventoryDelta(
        schema=body["schema"],
        guard_contracts=GUARD_CONTRACTS,
        entrypoints=ENTRYPOINTS,
        scanner_module=SCANNER_MODULE,
        scanner_class=SCANNER_CLASS,
        scanner_methods=SCANNER_METHODS,
        canonical_registry_integrated=False,
        closed=False,
        blockers=BLOCKERS,
        delta_sha256=canonical_sha(body),
    )


INVENTORY_DELTA = _build_delta()


def recognizes_recovery_consumption_method(
    module: str,
    class_name: str,
    method: str,
) -> bool:
    """Return whether the proposed scanner hook must classify this method."""

    return (
        module == SCANNER_MODULE
        and class_name == SCANNER_CLASS
        and method in SCANNER_METHODS
    )


__all__ = [
    "BLOCKERS",
    "ENTRYPOINTS",
    "GUARD_CONTRACTS",
    "GUARD_CONTRACT_IMPLEMENTED",
    "INVENTORY_DELTA",
    "PromotionRecoveryConsumptionInventoryDelta",
    "ProposedEntrypoint",
    "ProposedGuardContract",
    "SCANNER_CLASS",
    "SCANNER_METHODS",
    "SCANNER_MODULE",
    "recognizes_recovery_consumption_method",
]
