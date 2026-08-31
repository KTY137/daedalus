"""Neutral receipt-retention inventory types produced by a release gate."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from daedalus.spine.envelope import canonical_json


RETENTION_SOURCE_PATH = "daedalus/runtimes/provider_target_receipt_ledger.py"
RETENTION_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")


class ProviderTargetReceiptRetentionInventoryError(RuntimeError):
    """The retention inventory could not be produced without ambiguity."""


@dataclass(frozen=True, order=True)
class ProviderTargetReceiptRetentionSurface:
    function: str
    line: int
    column: int
    kind: str
    callee: str
    operation: str
    externally_reachable_via: str

    def __post_init__(self) -> None:
        if not self.function or any(ch.isspace() for ch in self.function):
            raise ValueError("surface function is invalid")
        if type(self.line) is not int or type(self.column) is not int:
            raise ValueError("surface position must use strict integers")
        if self.line < 1 or self.column < 0:
            raise ValueError("surface position is invalid")
        if self.kind not in {
            "schema_write",
            "event_store_write",
            "cas_write",
            "transitive_effectful_call",
        }:
            raise ValueError("surface kind is invalid")
        for label, value in (
            ("callee", self.callee),
            ("operation", self.operation),
            ("externally_reachable_via", self.externally_reachable_via),
        ):
            if not value or any(ch in value for ch in "\r\n"):
                raise ValueError(f"surface {label} is invalid")

    @property
    def blocking(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": RETENTION_SOURCE_PATH,
            "function": self.function,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "callee": self.callee,
            "operation": self.operation,
            "externally_reachable_via": self.externally_reachable_via,
            "wiring": "inventory_only",
            "guard_contract_bound": False,
            "effect_lease_consumed": False,
            "primary_checkout_target_proven": False,
            "blocking": True,
        }


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionInventory:
    source_revision: str
    source_sha256: str
    source_size: int
    surfaces: tuple[ProviderTargetReceiptRetentionSurface, ...]

    def __post_init__(self) -> None:
        if not _SOURCE_REVISION.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a lowercase 40-hex commit")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("source_sha256 must be lowercase sha256")
        if type(self.source_size) is not int or not (
            1 <= self.source_size <= RETENTION_MAX_SOURCE_BYTES
        ):
            raise ValueError("source_size is invalid")
        if not isinstance(self.surfaces, tuple) or not self.surfaces:
            raise ValueError("surfaces must be a non-empty immutable tuple")
        if self.surfaces != tuple(sorted(self.surfaces)):
            raise ValueError("surfaces must be sorted")
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("surfaces must be unique")
        positions = {(row.line, row.column) for row in self.surfaces}
        if len(positions) != len(self.surfaces):
            raise ValueError("surface source positions must be unique")

    @property
    def blockers(self) -> tuple[ProviderTargetReceiptRetentionSurface, ...]:
        return self.surfaces

    @property
    def closed(self) -> bool:
        return False

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-provider-target-receipt-retention-inventory/1",
            "source_revision": self.source_revision,
            "source_path": RETENTION_SOURCE_PATH,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "surfaces": [row.to_dict() for row in self.surfaces],
            "surface_count": len(self.surfaces),
            "blocker_count": len(self.blockers),
            "closed": False,
            "inventory_only": True,
            "canonical_inventory_integrated": False,
            "guard_contracts_complete": False,
            "effect_lease_semantics_verified": False,
            "primary_checkout_mutation_excluded": False,
            "blockers": [
                "provider-target-receipt-retention-surfaces-not-canonically-registered",
                "provider-target-receipt-retention-surfaces-not-guarded",
                "provider-target-receipt-retention-effect-lease-not-consumed",
                "provider-target-receipt-retention-primary-checkout-target-not-proven",
            ],
        }

    @property
    def digest(self) -> str:
        raw = canonical_json(self._payload()).encode("ascii")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}


__all__ = [
    "ProviderTargetReceiptRetentionInventory",
    "ProviderTargetReceiptRetentionInventoryError",
    "ProviderTargetReceiptRetentionSurface",
    "RETENTION_MAX_SOURCE_BYTES",
    "RETENTION_SOURCE_PATH",
]
