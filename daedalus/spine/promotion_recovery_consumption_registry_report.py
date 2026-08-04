"""Machine-readable status for recovery-consumption registry integration."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .envelope import canonical_sha
from .promotion_recovery_consumption_inventory import (
    ENTRYPOINTS as INVENTORY_ENTRYPOINTS,
    SCANNER_CLASS,
    SCANNER_METHODS,
    SCANNER_MODULE,
)


_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_EXPECTED_IDS = tuple(row.id for row in INVENTORY_ENTRYPOINTS)


@dataclass(frozen=True, slots=True)
class PromotionRecoveryConsumptionRegistryReport:
    schema: str
    source_revision: str
    canonical_registry_integrated: bool
    guard_contract_integrated: bool
    scanner_integrated: bool
    exact_rows: tuple[dict[str, object], ...]
    closed: bool
    blockers: tuple[str, ...]
    report_sha256: str

    def payload_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_revision": self.source_revision,
            "canonical_registry_integrated": self.canonical_registry_integrated,
            "guard_contract_integrated": self.guard_contract_integrated,
            "scanner_integrated": self.scanner_integrated,
            "exact_rows": list(self.exact_rows),
            "closed": self.closed,
            "blockers": list(self.blockers),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.payload_dict(), "report_sha256": self.report_sha256}


def _row_dict(row: Any) -> dict[str, object]:
    return {
        "id": row.id,
        "target": row.target,
        "surface": row.surface.value,
        "effects": [effect.value for effect in row.effects],
        "guard_contracts": list(row.guard_contracts),
        "wiring": row.wiring.value,
        "anchors": [asdict(anchor) for anchor in row.anchors],
        "migration": row.migration,
    }


def inspect_promotion_recovery_consumption_registry(
    *,
    source_revision: str,
    boundary: Any | None = None,
) -> PromotionRecoveryConsumptionRegistryReport:
    """Inspect only the exact reviewed integration boundary.

    The report deliberately does not claim that the two rows are central.  It
    proves the inventory delta reached the canonical registry and scanner while
    retaining the unguarded constructor and local-guard consumption blockers.
    """

    if not isinstance(source_revision, str) or not _REVISION.fullmatch(
        source_revision
    ):
        raise ValueError("source_revision must be a lowercase 40-64 hex revision")
    if boundary is None:
        from . import effect_boundary as boundary

    expected = {row.id: row for row in INVENTORY_ENTRYPOINTS}
    exact_rows: list[dict[str, object]] = []
    rows_exact = True
    for entrypoint_id in _EXPECTED_IDS:
        installed = boundary.REGISTRY_BY_ID.get(entrypoint_id)
        proposed = expected[entrypoint_id]
        if installed is None:
            rows_exact = False
            continue
        projected = _row_dict(installed)
        exact_rows.append(projected)
        if projected["target"] != proposed.target:
            rows_exact = False
        if projected["surface"] != proposed.surface:
            rows_exact = False
        if tuple(projected["effects"]) != proposed.effects:
            rows_exact = False
        if tuple(projected["guard_contracts"]) != proposed.guard_contracts:
            rows_exact = False
        if projected["wiring"] != proposed.wiring:
            rows_exact = False
        if projected["migration"] != proposed.migration:
            rows_exact = False
    rows_exact = rows_exact and tuple(
        row.id for row in boundary.ENTRYPOINTS[-len(_EXPECTED_IDS) :]
    ) == _EXPECTED_IDS

    guard_integrated = (
        boundary.GUARD_CONTRACT_IMPLEMENTED.get(
            "promotion.owner_recovery_decision"
        )
        is True
        and "promotion.owner_recovery_decision" in boundary.POLICY_CONTRACTS
    )
    classifier = boundary._surface_for_function
    scanner_integrated = (
        getattr(classifier, "__daedalus_scanner_module__", None)
        == SCANNER_MODULE
        and getattr(classifier, "__daedalus_scanner_class__", None)
        == SCANNER_CLASS
        and getattr(classifier, "__daedalus_scanner_methods__", None)
        == SCANNER_METHODS
    )
    integrated = rows_exact and guard_integrated and scanner_integrated

    blockers: list[str] = []
    if not rows_exact:
        blockers.append("canonical-effect-boundary-entrypoint-rows-not-exact")
    if not guard_integrated:
        blockers.append("owner-recovery-decision-guard-not-integrated")
    if not scanner_integrated:
        blockers.append("static-effect-scanner-hook-not-integrated")
    blockers.extend(
        (
            "constructor-performs-unguarded-schema-initialization",
            "consume-is-locally-owner-guarded-but-not-effect-lease-central",
            "runtime-conformance-kill-switch-and-docker-sandbox-not-composed",
        )
    )

    payload = {
        "schema": "daedalus-promotion-recovery-consumption-registry-report/1",
        "source_revision": source_revision,
        "canonical_registry_integrated": integrated,
        "guard_contract_integrated": guard_integrated,
        "scanner_integrated": scanner_integrated,
        "exact_rows": exact_rows,
        "closed": False,
        "blockers": blockers,
    }
    return PromotionRecoveryConsumptionRegistryReport(
        schema=payload["schema"],
        source_revision=source_revision,
        canonical_registry_integrated=integrated,
        guard_contract_integrated=guard_integrated,
        scanner_integrated=scanner_integrated,
        exact_rows=tuple(exact_rows),
        closed=False,
        blockers=tuple(blockers),
        report_sha256=canonical_sha(payload),
    )


__all__ = [
    "PromotionRecoveryConsumptionRegistryReport",
    "inspect_promotion_recovery_consumption_registry",
]
