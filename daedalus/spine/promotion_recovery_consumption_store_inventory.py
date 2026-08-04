"""Machine-readable inventory delta for the explicit recovery-consumption store initializer.

This packet is deliberately inert.  It describes the single newly introduced
filesystem-writing entrypoint and the exact static-scanner hook required to make
it visible, but it does not mutate the canonical effect registry or scanner.
The initializer therefore remains honestly unguarded until a later reviewed
packet composes persisted Effect-Lease, runtime-conformance, kill-switch and
sandbox authority.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from daedalus.spine.envelope import canonical_sha


BASE_REVISION = "27e8527c1eb811399f8d7ed2d60321ac37db1e9c"
_REVISION_RE = re.compile(r"[0-9a-f]{40,64}")


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
class PromotionRecoveryConsumptionStoreInventoryDelta:
    schema: str
    source_revision: str
    entrypoints: tuple[ProposedEntrypoint, ...]
    scanner_module: str
    scanner_function: str
    canonical_registry_integrated: bool
    canonical_scanner_integrated: bool
    closed: bool
    blockers: tuple[str, ...]
    delta_sha256: str

    def payload_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_revision": self.source_revision,
            "entrypoints": [asdict(row) for row in self.entrypoints],
            "scanner_module": self.scanner_module,
            "scanner_function": self.scanner_function,
            "canonical_registry_integrated": self.canonical_registry_integrated,
            "canonical_scanner_integrated": self.canonical_scanner_integrated,
            "closed": self.closed,
            "blockers": list(self.blockers),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.payload_dict(), "delta_sha256": self.delta_sha256}


SCANNER_MODULE = "daedalus.kernel.promotion_recovery_consumption_store"
SCANNER_FUNCTION = "initialize_promotion_recovery_consumption_store"

ENTRYPOINTS: tuple[ProposedEntrypoint, ...] = (
    ProposedEntrypoint(
        id="kernel.promotion_recovery_consumption_store.initialize",
        target=(
            "daedalus.kernel.promotion_recovery_consumption_store:"
            "initialize_promotion_recovery_consumption_store"
        ),
        surface="python",
        effects=("filesystem_write",),
        guard_contracts=(),
        wiring="unguarded",
        anchors=(
            "tempfile.mkstemp",
            "sqlite3.connect",
            "os.link",
            "_fsync_file",
            "_fsync_directory",
        ),
        migration=(
            "Register this explicit initializer, then require the exact persisted "
            "Effect Lease, current RuntimeConformanceReceipt, kill-switch state and "
            "Docker sandbox capability before any production caller may invoke it."
        ),
    ),
)

BLOCKERS = (
    "canonical-effect-boundary-entrypoint-row-not-yet-integrated",
    "static-effect-scanner-does-not-yet-classify-explicit-store-initializer",
    "explicit-store-initializer-remains-unguarded",
    "initializer-not-bound-to-persisted-effect-lease",
    "initializer-not-bound-to-runtime-conformance-kill-switch-or-docker-sandbox",
    "production-callers-not-yet-migrated-to-preprovisioned-store",
    "legacy-auto-initializing-constructor-remains-production-visible",
)


def recognizes_recovery_consumption_store_initializer(
    module: str,
    function: str,
) -> bool:
    """Return whether the proposed scanner hook must classify this function."""

    return module == SCANNER_MODULE and function == SCANNER_FUNCTION


def build_promotion_recovery_consumption_store_inventory_delta(
    source_revision: str,
) -> PromotionRecoveryConsumptionStoreInventoryDelta:
    """Build the exact parent-revision-bound inventory delta.

    A different but syntactically valid revision is stale for this packet and is
    refused rather than silently relabeling the reviewed source anchors.
    """

    if type(source_revision) is not str or _REVISION_RE.fullmatch(source_revision) is None:
        raise ValueError("source revision must be lowercase 40-64 hexadecimal characters")
    if source_revision != BASE_REVISION:
        raise ValueError("source revision is stale for this inventory delta")
    body = {
        "schema": "daedalus-promotion-recovery-consumption-store-inventory-delta/1",
        "source_revision": source_revision,
        "entrypoints": [asdict(row) for row in ENTRYPOINTS],
        "scanner_module": SCANNER_MODULE,
        "scanner_function": SCANNER_FUNCTION,
        "canonical_registry_integrated": False,
        "canonical_scanner_integrated": False,
        "closed": False,
        "blockers": list(BLOCKERS),
    }
    return PromotionRecoveryConsumptionStoreInventoryDelta(
        schema=body["schema"],
        source_revision=source_revision,
        entrypoints=ENTRYPOINTS,
        scanner_module=SCANNER_MODULE,
        scanner_function=SCANNER_FUNCTION,
        canonical_registry_integrated=False,
        canonical_scanner_integrated=False,
        closed=False,
        blockers=BLOCKERS,
        delta_sha256=canonical_sha(body),
    )


INVENTORY_DELTA = build_promotion_recovery_consumption_store_inventory_delta(
    BASE_REVISION
)


__all__ = [
    "BASE_REVISION",
    "BLOCKERS",
    "ENTRYPOINTS",
    "INVENTORY_DELTA",
    "PromotionRecoveryConsumptionStoreInventoryDelta",
    "ProposedEntrypoint",
    "SCANNER_FUNCTION",
    "SCANNER_MODULE",
    "build_promotion_recovery_consumption_store_inventory_delta",
    "recognizes_recovery_consumption_store_initializer",
]
