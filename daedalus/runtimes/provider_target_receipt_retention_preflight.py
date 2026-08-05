"""Read-only admission preflight for provider-target receipt retention.

This module composes the exact signed retention-operation authority with a live
repository-HEAD receipt and a freshly rebuilt retention-write inventory.  It is
intentionally not the effectful retention entrypoint: it does not inspect the
persisted Effect-Lease ledger, begin an effect, register an entrypoint, open
SQLite, publish CAS bytes, or invoke ``ProviderTargetReceiptLedger.retain``.

The returned receipt proves only that the inert subjects agree on one current
revision and that the signed guard contract authenticated before repository
reads.  A later central packet must consume persisted Effect-Lease authority and
this exact preflight receipt immediately before the retention write.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from daedalus.gates.provider_target_receipt_retention_inventory import (
    ProviderTargetReceiptRetentionInventory,
    ProviderTargetReceiptRetentionInventoryError,
    scan_provider_target_receipt_retention,
)
from daedalus.gates.repository_head_revision import (
    RepositoryHeadRevisionError,
    RepositoryHeadRevisionReceipt,
    verify_repository_head_revision_receipt,
)
from daedalus.kernel.contracts import EffectLease
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_GUARD_CONTRACT,
    ProviderTargetReceiptRetentionContractError,
    ProviderTargetReceiptRetentionOperationAuthority,
    ProviderTargetReceiptRetentionOperationSubject,
    authorize_provider_target_receipt_retention_operation,
    build_provider_target_receipt_retention_operation_subject,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
)
from daedalus.schemas import _repo_path, _revision, _sha256
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.envelope import canonical_sha


class ProviderTargetReceiptRetentionPreflightError(RuntimeError):
    """Base class for retention-preflight refusal."""


class ProviderTargetReceiptRetentionPreflightShapeError(
    ProviderTargetReceiptRetentionPreflightError
):
    """A supplied subject or retained preflight receipt is malformed."""


class ProviderTargetReceiptRetentionPreflightBindingError(
    ProviderTargetReceiptRetentionPreflightError
):
    """Authenticated revision, inventory, guard, or receipt material differs."""


def _strict_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ProviderTargetReceiptRetentionPreflightShapeError(
            f"{label} must be a positive strict integer"
        )
    return value


def _digest(value: Any, label: str) -> str:
    try:
        return _sha256(value, label)
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionPreflightShapeError(
            f"{label} must be lowercase sha256"
        ) from exc


def _source_revision(value: Any) -> str:
    try:
        return _revision(value, "source_revision")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionPreflightShapeError(
            "source_revision must be a lowercase 40-hex revision"
        ) from exc


def _scope_path(value: Any, label: str) -> str:
    try:
        path = _repo_path(value, label)
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionPreflightShapeError(
            f"{label} is malformed"
        ) from exc
    if path == ".":
        raise ProviderTargetReceiptRetentionPreflightShapeError(
            f"{label} must not name the repository root"
        )
    return path


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionPreflightReceipt:
    """Canonical read-only receipt for one exact retention preflight."""

    source_revision: str
    repository_head_receipt_sha256: str
    provider_target_receipt_sha256: str
    retention_inventory_sha256: str
    retention_inventory_source_sha256: str
    retention_inventory_source_size: int
    retention_inventory_surface_count: int
    retention_authority_sha256: str
    retention_subject_sha256: str
    retention_execution_request_sha256: str
    retention_effect_lease_sha256: str
    guard_contract: str
    guard_evidence: str
    event_store_scope_path: str
    receipt_cas_scope_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_revision", _source_revision(self.source_revision))
        for field in (
            "repository_head_receipt_sha256",
            "provider_target_receipt_sha256",
            "retention_inventory_sha256",
            "retention_inventory_source_sha256",
            "retention_authority_sha256",
            "retention_subject_sha256",
            "retention_execution_request_sha256",
            "retention_effect_lease_sha256",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        _strict_positive_int(
            self.retention_inventory_source_size,
            "retention_inventory_source_size",
        )
        _strict_positive_int(
            self.retention_inventory_surface_count,
            "retention_inventory_surface_count",
        )
        if self.guard_contract != RETENTION_GUARD_CONTRACT:
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                "guard_contract is not the exact retention guard"
            )
        expected_evidence = (
            f"authority_sha256={self.retention_authority_sha256};"
            f"subject_sha256={self.retention_subject_sha256}"
        )
        if self.guard_evidence != expected_evidence:
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                "guard_evidence does not bind authority and subject"
            )
        object.__setattr__(
            self,
            "event_store_scope_path",
            _scope_path(self.event_store_scope_path, "event_store_scope_path"),
        )
        object.__setattr__(
            self,
            "receipt_cas_scope_path",
            _scope_path(self.receipt_cas_scope_path, "receipt_cas_scope_path"),
        )
        if self.event_store_scope_path == self.receipt_cas_scope_path:
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                "retention scope paths must differ"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-target-receipt-retention-preflight/1",
            "source_revision": self.source_revision,
            "repository_head_receipt_sha256": self.repository_head_receipt_sha256,
            "provider_target_receipt_sha256": self.provider_target_receipt_sha256,
            "retention_inventory_sha256": self.retention_inventory_sha256,
            "retention_inventory_source_sha256": self.retention_inventory_source_sha256,
            "retention_inventory_source_size": self.retention_inventory_source_size,
            "retention_inventory_surface_count": self.retention_inventory_surface_count,
            "retention_authority_sha256": self.retention_authority_sha256,
            "retention_subject_sha256": self.retention_subject_sha256,
            "retention_execution_request_sha256": self.retention_execution_request_sha256,
            "retention_effect_lease_sha256": self.retention_effect_lease_sha256,
            "guard_contract": self.guard_contract,
            "guard_evidence": self.guard_evidence,
            "event_store_scope_path": self.event_store_scope_path,
            "receipt_cas_scope_path": self.receipt_cas_scope_path,
            "repository_head_reverified": True,
            "retention_inventory_rebuilt": True,
            "retention_authority_authenticated": True,
            "guard_decision_allowed": True,
            "provider_execution_allowed": False,
            "persisted_effect_lease_verified": False,
            "retention_effect_started": False,
            "retention_write_performed": False,
            "canonical_entrypoint_registered": False,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionPreflightReceipt":
        fields = {
            "source_revision",
            "repository_head_receipt_sha256",
            "provider_target_receipt_sha256",
            "retention_inventory_sha256",
            "retention_inventory_source_sha256",
            "retention_inventory_source_size",
            "retention_inventory_surface_count",
            "retention_authority_sha256",
            "retention_subject_sha256",
            "retention_execution_request_sha256",
            "retention_effect_lease_sha256",
            "guard_contract",
            "guard_evidence",
            "event_store_scope_path",
            "receipt_cas_scope_path",
        }
        exact = {
            "schema",
            *fields,
            "repository_head_reverified",
            "retention_inventory_rebuilt",
            "retention_authority_authenticated",
            "guard_decision_allowed",
            "provider_execution_allowed",
            "persisted_effect_lease_verified",
            "retention_effect_started",
            "retention_write_performed",
            "canonical_entrypoint_registered",
            "gate_transition_authorized",
            "closed",
        }
        if not isinstance(payload, Mapping) or set(payload) != exact:
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                "retention preflight receipt fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-target-receipt-retention-preflight/1":
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                "retention preflight receipt schema does not match"
            )
        for field in (
            "repository_head_reverified",
            "retention_inventory_rebuilt",
            "retention_authority_authenticated",
            "guard_decision_allowed",
        ):
            if payload[field] is not True:
                raise ProviderTargetReceiptRetentionPreflightShapeError(
                    f"retention preflight receipt must retain {field}"
                )
        for field in (
            "provider_execution_allowed",
            "persisted_effect_lease_verified",
            "retention_effect_started",
            "retention_write_performed",
            "canonical_entrypoint_registered",
            "gate_transition_authorized",
            "closed",
        ):
            if payload[field] is not False:
                raise ProviderTargetReceiptRetentionPreflightShapeError(
                    f"retention preflight receipt contains unsupported claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionPreflightError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                "retention preflight receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def verify_provider_target_receipt_retention_preflight(
    repository_root: Path,
    repository_head_receipt: RepositoryHeadRevisionReceipt,
    receipt: ProviderExecutableTargetVerificationReceipt,
    inventory: ProviderTargetReceiptRetentionInventory,
    authority: ProviderTargetReceiptRetentionOperationAuthority,
    execution: EffectExecutionRequest,
    effect_lease: EffectLease,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
    at: datetime,
) -> ProviderTargetReceiptRetentionPreflightReceipt:
    """Authenticate and revision-bind one inert retention request.

    Authority authentication is deliberately completed before repository reads.
    The live HEAD receipt and retention inventory are then rebuilt from the exact
    repository root.  No retained Effect-Lease state is inspected or changed.
    """

    if not isinstance(repository_root, Path):
        raise ProviderTargetReceiptRetentionPreflightShapeError(
            "repository_root must be pathlib.Path"
        )
    exact_types = (
        (repository_head_receipt, RepositoryHeadRevisionReceipt, "repository_head_receipt"),
        (receipt, ProviderExecutableTargetVerificationReceipt, "receipt"),
        (inventory, ProviderTargetReceiptRetentionInventory, "inventory"),
        (authority, ProviderTargetReceiptRetentionOperationAuthority, "authority"),
        (execution, EffectExecutionRequest, "execution"),
        (effect_lease, EffectLease, "effect_lease"),
    )
    for value, expected_type, label in exact_types:
        if type(value) is not expected_type:
            raise ProviderTargetReceiptRetentionPreflightShapeError(
                f"{label} must be exact {expected_type.__name__}"
            )

    try:
        expected_subject = build_provider_target_receipt_retention_operation_subject(
            receipt=receipt,
            retention_inventory_sha256=inventory.digest,
            retention_inventory_source_revision=inventory.source_revision,
            retention_inventory_source_sha256=inventory.source_sha256,
            execution=execution,
            effect_lease=effect_lease,
            event_store_scope_path=event_store_scope_path,
            receipt_cas_scope_path=receipt_cas_scope_path,
        )
        decision = authorize_provider_target_receipt_retention_operation(
            authority,
            expected_authority_id=expected_authority_id,
            authority_keyring=authority_keyring,
            expected_subject=expected_subject,
            at=at,
        )
    except ProviderTargetReceiptRetentionContractError as exc:
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "retention operation authority did not authenticate"
        ) from exc

    if type(expected_subject) is not ProviderTargetReceiptRetentionOperationSubject:
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "retention subject builder returned a non-exact subject"
        )
    expected_evidence = (
        f"authority_sha256={authority.digest};"
        f"subject_sha256={expected_subject.digest}"
    )
    if (
        type(decision) is not GuardDecision
        or decision.contract != RETENTION_GUARD_CONTRACT
        or decision.allowed is not True
        or decision.evidence != expected_evidence
    ):
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "retention guard decision is detached from signed authority"
        )

    try:
        verify_repository_head_revision_receipt(
            repository_root,
            receipt.source_revision,
            repository_head_receipt,
        )
    except RepositoryHeadRevisionError as exc:
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "repository HEAD receipt did not reverify"
        ) from exc

    try:
        rebuilt_inventory = scan_provider_target_receipt_retention(
            repository_root,
            source_revision=receipt.source_revision,
        )
    except ProviderTargetReceiptRetentionInventoryError as exc:
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "retention inventory could not be rebuilt"
        ) from exc
    if type(rebuilt_inventory) is not ProviderTargetReceiptRetentionInventory:
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "retention inventory scanner returned a non-exact inventory"
        )
    if rebuilt_inventory != inventory or rebuilt_inventory.digest != inventory.digest:
        raise ProviderTargetReceiptRetentionPreflightBindingError(
            "retention inventory differs from current repository bytes"
        )

    return ProviderTargetReceiptRetentionPreflightReceipt(
        source_revision=receipt.source_revision,
        repository_head_receipt_sha256=repository_head_receipt.digest,
        provider_target_receipt_sha256=receipt.digest,
        retention_inventory_sha256=inventory.digest,
        retention_inventory_source_sha256=inventory.source_sha256,
        retention_inventory_source_size=inventory.source_size,
        retention_inventory_surface_count=len(inventory.surfaces),
        retention_authority_sha256=authority.digest,
        retention_subject_sha256=expected_subject.digest,
        retention_execution_request_sha256=execution.digest,
        retention_effect_lease_sha256=effect_lease.digest,
        guard_contract=decision.contract,
        guard_evidence=decision.evidence,
        event_store_scope_path=expected_subject.event_store_scope_path,
        receipt_cas_scope_path=expected_subject.receipt_cas_scope_path,
    )


__all__ = [
    "ProviderTargetReceiptRetentionPreflightBindingError",
    "ProviderTargetReceiptRetentionPreflightError",
    "ProviderTargetReceiptRetentionPreflightReceipt",
    "ProviderTargetReceiptRetentionPreflightShapeError",
    "verify_provider_target_receipt_retention_preflight",
]
