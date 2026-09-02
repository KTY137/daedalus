"""Read-only verification of completed provider-target receipt retention.

This module composes an exact completed admission/recovery identity with live
canonical Event-Store and receipt-CAS reads. It authenticates the retained
provider-target verification receipt against its signed authority and exact
source tree, rechecks stable filesystem identities around every retained-state
read, and emits a deterministic evidence receipt for the observed state.

The verifier deliberately does not inspect or mutate the Effect-Lease ledger.
The retained Effect terminal receipt remains separately required before a
future central execution packet may claim completion of the leased effect.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.contracts.base import _revision, _sha256
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetAuthority,
    ProviderExecutableTargetManifest,
    ProviderExecutableTargetProjection,
)
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderInvocationRegistryManifest,
)
from daedalus.runtimes.provider_target_receipt_ledger import (
    ProviderTargetReceiptLedger,
    ProviderTargetReceiptRetentionError,
    ProviderTargetReceiptRetentionStateError,
    _effect_key,
    _read_intent,
    _receipt_bytes,
    _validate_topology,
)
from daedalus.runtimes.provider_target_receipt_retention_admission import (
    ProviderTargetReceiptRetentionAdmissionError,
    ProviderTargetReceiptRetentionAdmissionReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_recovery import (
    ProviderTargetReceiptRetentionRecoveryDecision,
    ProviderTargetReceiptRetentionRecoveryError,
)
from daedalus.runtimes.provider_target_verification import (
    verify_provider_target_verification_receipt,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    ProviderTargetVerificationError,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.ledger import STATE_COMPLETED

_SCHEMA = "daedalus-provider-target-receipt-retention-completed-evidence/1"
_DIGEST_FIELDS = (
    "admission_sha256",
    "recovery_decision_sha256",
    "provider_target_receipt_sha256",
    "target_projection_sha256",
    "receipt_artifact_sha256",
    "retention_intent_payload_sha256",
    "retention_event_evidence_sha256",
    "retention_topology_identity_sha256",
    "receipt_artifact_file_identity_sha256",
    "start_receipt_sha256",
    "terminal_receipt_sha256",
)
_FALSE_CLAIMS = (
    "persisted_effect_terminal_verified",
    "automatic_reexecution_allowed",
    "effect_start_authorized",
    "retention_write_authorized",
    "effect_terminalization_authorized",
    "canonical_entrypoint_registered",
    "gate_transition_authorized",
    "closed",
)


class ProviderTargetReceiptRetentionCompletedEvidenceError(RuntimeError):
    """Base class for completed-retention evidence refusal."""


class ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
    ProviderTargetReceiptRetentionCompletedEvidenceError
):
    """An input or evidence receipt has a malformed or non-exact shape."""


class ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
    ProviderTargetReceiptRetentionCompletedEvidenceError
):
    """Admission, recovery, receipt, Event-Store or CAS evidence disagrees."""


def _commit_revision(value: Any, label: str) -> str:
    try:
        revision = _revision(value, label)
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
            f"{label} is malformed"
        ) from exc
    if len(revision) != 40:
        raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
            f"{label} must be an exact 40-hex commit revision"
        )
    return revision


def _bounded_path(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
            f"{label} must be a bounded exact path string"
        )
    return value


def _contains_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current = current / part
        if current.is_symlink():
            return True
    return False


def _path_identity(path: Path, label: str, *, directory: bool) -> dict[str, Any]:
    try:
        absolute = Path(os.path.abspath(os.fspath(path)))
        if _contains_symlink(absolute):
            raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
                f"{label} path must not contain symlinks"
            )
        resolved = absolute.resolve(strict=True)
        info = resolved.stat()
    except ProviderTargetReceiptRetentionCompletedEvidenceError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            f"{label} cannot be resolved"
        ) from exc
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
                f"{label} must be a real directory"
            )
    else:
        if not stat.S_ISREG(info.st_mode):
            raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
                f"{label} must be a real regular file"
            )
        if info.st_nlink != 1:
            raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
                f"{label} must have one filesystem identity"
            )
    return {
        "path": os.fspath(resolved),
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
    }


def _topology_identity(
    retention_ledger: ProviderTargetReceiptLedger,
) -> dict[str, dict[str, Any]]:
    try:
        _validate_topology(
            retention_ledger.primary_checkout,
            retention_ledger.source_store,
            retention_ledger.spine,
        )
    except ProviderTargetReceiptRetentionError as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention topology did not verify"
        ) from exc
    return {
        "primary_checkout": _path_identity(
            Path(retention_ledger.primary_checkout),
            "Primary Checkout",
            directory=True,
        ),
        "event_store": _path_identity(
            Path(retention_ledger.spine.path),
            "canonical Event Store",
            directory=False,
        ),
        "receipt_cas": _path_identity(
            Path(retention_ledger.source_store.root),
            "receipt CAS",
            directory=True,
        ),
    }


def _bind_admission_topology(
    admission: ProviderTargetReceiptRetentionAdmissionReceipt,
    observed: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    for field in (
        "primary_checkout_path",
        "retention_root_path",
        "event_store_path",
        "receipt_cas_path",
    ):
        if not Path(getattr(admission, field)).is_absolute():
            raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
                f"{field} is not an absolute admission path"
            )
    expected = {
        "primary_checkout": _path_identity(
            Path(admission.primary_checkout_path),
            "admission Primary Checkout",
            directory=True,
        ),
        "event_store": _path_identity(
            Path(admission.event_store_path),
            "admission canonical Event Store",
            directory=False,
        ),
        "receipt_cas": _path_identity(
            Path(admission.receipt_cas_path),
            "admission receipt CAS",
            directory=True,
        ),
    }
    for key in ("primary_checkout", "event_store", "receipt_cas"):
        if expected[key] != observed[key]:
            raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
                f"live {key} identity is detached from the retention admission"
            )

    root = _path_identity(
        Path(admission.retention_root_path),
        "admission retention root",
        directory=True,
    )
    root_path = Path(root["path"])
    primary_path = Path(observed["primary_checkout"]["path"])
    event_path = Path(observed["event_store"]["path"])
    cas_path = Path(observed["receipt_cas"]["path"])
    if (
        root_path == primary_path
        or root_path in primary_path.parents
        or primary_path in root_path.parents
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "admission retention root overlaps the Primary Checkout"
        )
    if root_path not in event_path.parents or root_path not in cas_path.parents:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "admission retention root does not contain Event Store and receipt CAS"
        )
    return {
        "primary_checkout": observed["primary_checkout"],
        "retention_root": root,
        "event_store": observed["event_store"],
        "receipt_cas": observed["receipt_cas"],
    }


def _artifact_file_identity(
    retention_ledger: ProviderTargetReceiptLedger,
    artifact: ArtifactRef,
) -> dict[str, Any]:
    try:
        object_path = retention_ledger.source_store._object_path(artifact.sha256)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "receipt CAS cannot derive the retained artifact path"
        ) from exc
    return _path_identity(
        Path(object_path),
        "retained receipt artifact",
        directory=False,
    )


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionCompletedEvidenceReceipt:
    """Canonical read-only evidence for one completed retained receipt."""

    source_revision: str
    admission_sha256: str
    recovery_decision_sha256: str
    provider_target_receipt_sha256: str
    target_projection_sha256: str
    receipt_artifact_sha256: str
    retention_intent_id: int
    retention_intent_payload_sha256: str
    retention_event_evidence_sha256: str
    retention_topology_identity_sha256: str
    receipt_artifact_file_identity_sha256: str
    start_receipt_sha256: str
    terminal_receipt_sha256: str
    event_store_path: str
    receipt_cas_path: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "source_revision",
                _commit_revision(self.source_revision, "source_revision"),
            )
            for field in _DIGEST_FIELDS:
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "event_store_path",
                _bounded_path(self.event_store_path, "event_store_path"),
            )
            object.__setattr__(
                self,
                "receipt_cas_path",
                _bounded_path(self.receipt_cas_path, "receipt_cas_path"),
            )
        except ProviderTargetReceiptRetentionCompletedEvidenceError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                "completed retention evidence receipt is malformed"
            ) from exc
        if (
            isinstance(self.retention_intent_id, bool)
            or not isinstance(self.retention_intent_id, int)
            or self.retention_intent_id < 1
        ):
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                "retention_intent_id must be a positive integer"
            )
        if self.receipt_artifact_sha256 != self.provider_target_receipt_sha256:
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                "receipt artifact must address the provider-target receipt"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "source_revision": self.source_revision,
            "admission_sha256": self.admission_sha256,
            "recovery_decision_sha256": self.recovery_decision_sha256,
            "provider_target_receipt_sha256": self.provider_target_receipt_sha256,
            "target_projection_sha256": self.target_projection_sha256,
            "receipt_artifact_sha256": self.receipt_artifact_sha256,
            "retention_intent_id": self.retention_intent_id,
            "retention_intent_payload_sha256": (
                self.retention_intent_payload_sha256
            ),
            "retention_event_evidence_sha256": (
                self.retention_event_evidence_sha256
            ),
            "retention_topology_identity_sha256": (
                self.retention_topology_identity_sha256
            ),
            "receipt_artifact_file_identity_sha256": (
                self.receipt_artifact_file_identity_sha256
            ),
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "event_store_path": self.event_store_path,
            "receipt_cas_path": self.receipt_cas_path,
            "admission_identity_bound": True,
            "admission_topology_bound": True,
            "recovery_decision_bound": True,
            "provider_target_receipt_authenticated": True,
            "retention_intent_completed": True,
            "retained_receipt_cas_verified": True,
            "primary_checkout_disjointness_verified": True,
            "retention_topology_stable": True,
            "receipt_artifact_identity_stable": True,
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionCompletedEvidenceReceipt":
        fields = {
            "source_revision",
            *_DIGEST_FIELDS,
            "retention_intent_id",
            "event_store_path",
            "receipt_cas_path",
        }
        true_claims = {
            "admission_identity_bound",
            "admission_topology_bound",
            "recovery_decision_bound",
            "provider_target_receipt_authenticated",
            "retention_intent_completed",
            "retained_receipt_cas_verified",
            "primary_checkout_disjointness_verified",
            "retention_topology_stable",
            "receipt_artifact_identity_stable",
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *true_claims,
            *_FALSE_CLAIMS,
        }:
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                "completed retention evidence fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                "completed retention evidence schema is wrong"
            )
        for field in true_claims:
            if payload[field] is not True:
                raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                    f"completed retention evidence lost required claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                    f"completed retention evidence contains unsupported claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionCompletedEvidenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                "completed retention evidence receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _canonical_subjects(
    admission: ProviderTargetReceiptRetentionAdmissionReceipt,
    recovery: ProviderTargetReceiptRetentionRecoveryDecision,
) -> tuple[
    dict[str, Any],
    ProviderTargetReceiptRetentionAdmissionReceipt,
    dict[str, Any],
    ProviderTargetReceiptRetentionRecoveryDecision,
]:
    try:
        admission_payload = admission.to_dict()
        restored_admission = ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(
            admission_payload
        )
        recovery_payload = recovery.to_dict()
        restored_recovery = ProviderTargetReceiptRetentionRecoveryDecision.from_dict(
            recovery_payload
        )
    except (
        ProviderTargetReceiptRetentionAdmissionError,
        ProviderTargetReceiptRetentionRecoveryError,
    ) as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention admission or recovery decision is noncanonical"
        ) from exc
    if restored_admission != admission or restored_recovery != recovery:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention admission or recovery reconstruction changed its subject"
        )
    return (
        admission_payload,
        restored_admission,
        recovery_payload,
        restored_recovery,
    )


def verify_provider_target_receipt_retention_completed_evidence(
    admission: ProviderTargetReceiptRetentionAdmissionReceipt,
    recovery: ProviderTargetReceiptRetentionRecoveryDecision,
    retention_ledger: ProviderTargetReceiptLedger,
    receipt: ProviderExecutableTargetVerificationReceipt,
    target_authority: ProviderExecutableTargetAuthority,
    invocation_authority: ProviderInvocationObservationAuthority,
    identity_registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    target_manifest: ProviderExecutableTargetManifest,
    source_tree_ref: ArtifactRef,
    *,
    expected_source_revision: str,
    target_contract_id: str,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    verifier_id: str,
    verifier_keyring: Mapping[str, bytes | str],
    at: Any,
    max_source_bytes: int = 4 * 1024 * 1024,
) -> ProviderTargetReceiptRetentionCompletedEvidenceReceipt:
    """Authenticate and re-read one completed retained receipt without writes."""

    exact = (
        (
            admission,
            ProviderTargetReceiptRetentionAdmissionReceipt,
            "admission",
        ),
        (
            recovery,
            ProviderTargetReceiptRetentionRecoveryDecision,
            "recovery",
        ),
        (retention_ledger, ProviderTargetReceiptLedger, "retention_ledger"),
        (
            receipt,
            ProviderExecutableTargetVerificationReceipt,
            "receipt",
        ),
        (
            target_authority,
            ProviderExecutableTargetAuthority,
            "target_authority",
        ),
        (
            invocation_authority,
            ProviderInvocationObservationAuthority,
            "invocation_authority",
        ),
        (
            identity_registry,
            ProviderInvocationRegistryManifest,
            "identity_registry",
        ),
        (execution, EffectExecutionRequest, "execution"),
        (
            target_manifest,
            ProviderExecutableTargetManifest,
            "target_manifest",
        ),
        (source_tree_ref, ArtifactRef, "source_tree_ref"),
    )
    for value, expected, label in exact:
        if type(value) is not expected:
            raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
                f"{label} must be exact {expected.__name__}"
            )
    if (
        isinstance(max_source_bytes, bool)
        or not isinstance(max_source_bytes, int)
        or max_source_bytes < 1
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceShapeError(
            "max_source_bytes must be a positive integer"
        )
    revision = _commit_revision(
        expected_source_revision,
        "expected_source_revision",
    )
    (
        admission_payload,
        restored_admission,
        recovery_payload,
        restored_recovery,
    ) = _canonical_subjects(admission, recovery)

    if admission.source_revision != revision or recovery.source_revision != revision:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "completed retention evidence belongs to a stale source revision"
        )
    if admission.execution_state != "COMPLETED":
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention admission is not completed"
        )
    if (
        recovery.execution_state != "COMPLETED"
        or recovery.decision != "verify_completed_retention_evidence"
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "recovery decision does not request completed evidence verification"
        )
    if recovery.admission_sha256 != admission.digest:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "recovery decision is detached from the retention admission"
        )
    if admission.provider_target_receipt_sha256 != receipt.digest:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention admission names a different provider-target receipt"
        )
    if (
        admission.start_receipt_sha256 is None
        or admission.terminal_receipt_sha256 is None
        or recovery.start_receipt_sha256 != admission.start_receipt_sha256
        or recovery.terminal_receipt_sha256 != admission.terminal_receipt_sha256
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "completed execution receipt identities are detached"
        )

    artifact = ArtifactRef.from_sha256(receipt.digest)
    topology_before = _bind_admission_topology(
        admission,
        _topology_identity(retention_ledger),
    )
    artifact_identity_before = _artifact_file_identity(retention_ledger, artifact)

    try:
        projection = verify_provider_target_verification_receipt(
            receipt,
            target_authority,
            invocation_authority,
            identity_registry,
            execution,
            target_manifest,
            retention_ledger.source_store,
            source_tree_ref,
            target_contract_id=target_contract_id,
            authority_id=authority_id,
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            verifier_id=verifier_id,
            verifier_keyring=verifier_keyring,
            at=at,
            max_source_bytes=max_source_bytes,
        )
    except ProviderTargetVerificationError as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "provider-target receipt did not authenticate"
        ) from exc
    if type(projection) is not ProviderExecutableTargetProjection:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "provider-target verification returned a non-exact projection"
        )

    topology_mid = _bind_admission_topology(
        admission,
        _topology_identity(retention_ledger),
    )
    artifact_identity_mid = _artifact_file_identity(retention_ledger, artifact)
    if (
        topology_mid != topology_before
        or artifact_identity_mid != artifact_identity_before
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention topology changed during receipt authentication"
        )

    try:
        payload = _receipt_bytes(receipt)
        intent = _read_intent(
            retention_ledger.spine.path,
            _effect_key(receipt.digest),
        )
        if intent is None:
            raise ProviderTargetReceiptRetentionStateError(
                "completed receipt has no canonical retention intent"
            )
        retention_ledger._validate_completed(intent, receipt, artifact, payload)

        topology_after = _bind_admission_topology(
            admission,
            _topology_identity(retention_ledger),
        )
        artifact_identity_after = _artifact_file_identity(
            retention_ledger,
            artifact,
        )
        final_intent = _read_intent(
            retention_ledger.spine.path,
            _effect_key(receipt.digest),
        )
        if final_intent is None:
            raise ProviderTargetReceiptRetentionStateError(
                "completed receipt disappeared during verification"
            )
        retention_ledger._validate_completed(
            final_intent,
            receipt,
            artifact,
            payload,
        )
        topology_final = _bind_admission_topology(
            admission,
            _topology_identity(retention_ledger),
        )
        artifact_identity_final = _artifact_file_identity(
            retention_ledger,
            artifact,
        )
    except ProviderTargetReceiptRetentionError as exc:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "completed retention Event-Store or CAS evidence did not verify"
        ) from exc

    if (
        topology_after != topology_before
        or artifact_identity_after != artifact_identity_before
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention topology changed between completed-state reads"
        )
    if (
        topology_final != topology_before
        or artifact_identity_final != artifact_identity_before
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention topology changed during final completed-state read"
        )
    if intent != final_intent or final_intent.state != STATE_COMPLETED:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "completed retention state changed during verification"
        )
    if final_intent.payload_sha != intent.payload_sha:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention intent payload identity changed during verification"
        )
    if final_intent.effect_id != artifact.sha256:
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "retention terminal effect identity differs from the receipt artifact"
        )

    final_subjects = _canonical_subjects(admission, recovery)
    if (
        final_subjects[0] != admission_payload
        or final_subjects[1] != restored_admission
        or final_subjects[2] != recovery_payload
        or final_subjects[3] != restored_recovery
        or admission.digest != recovery.admission_sha256
        or receipt.digest != artifact.sha256
    ):
        raise ProviderTargetReceiptRetentionCompletedEvidenceBindingError(
            "completed retention subjects changed during verification"
        )

    event_evidence = canonical_sha(
        {
            "intent_id": final_intent.id,
            "kind": final_intent.kind,
            "effect_key": final_intent.effect_key,
            "payload_sha256": final_intent.payload_sha,
            "state": final_intent.state,
            "resolved_ts": final_intent.resolved_ts,
            "effect_id": final_intent.effect_id,
            "result": final_intent.result,
            "trace_id": final_intent.trace_id,
        }
    )
    topology_digest = canonical_sha(topology_final)
    artifact_identity_digest = canonical_sha(artifact_identity_final)
    return ProviderTargetReceiptRetentionCompletedEvidenceReceipt(
        source_revision=revision,
        admission_sha256=admission.digest,
        recovery_decision_sha256=recovery.digest,
        provider_target_receipt_sha256=receipt.digest,
        target_projection_sha256=projection.digest,
        receipt_artifact_sha256=artifact.sha256,
        retention_intent_id=final_intent.id,
        retention_intent_payload_sha256=final_intent.payload_sha,
        retention_event_evidence_sha256=event_evidence,
        retention_topology_identity_sha256=topology_digest,
        receipt_artifact_file_identity_sha256=artifact_identity_digest,
        start_receipt_sha256=admission.start_receipt_sha256,
        terminal_receipt_sha256=admission.terminal_receipt_sha256,
        event_store_path=topology_final["event_store"]["path"],
        receipt_cas_path=topology_final["receipt_cas"]["path"],
    )


__all__ = [
    "ProviderTargetReceiptRetentionCompletedEvidenceBindingError",
    "ProviderTargetReceiptRetentionCompletedEvidenceError",
    "ProviderTargetReceiptRetentionCompletedEvidenceReceipt",
    "ProviderTargetReceiptRetentionCompletedEvidenceShapeError",
    "verify_provider_target_receipt_retention_completed_evidence",
]
