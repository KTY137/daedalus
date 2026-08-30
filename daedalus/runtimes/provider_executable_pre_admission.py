"""Bind provider executable evidence before any code-loading boundary.

This module closes one narrow gap between the authenticated provider-identity /
target-evidence stack and a future guarded executable loader.  It composes only
already-issued, non-executing receipts and proves that they describe one exact
provider implementation, one exact runtime effect subject, one retained target
receipt, and the repository revision that is still HEAD.

The resulting receipt is deliberately *not* executable authority.  It loads no
module, accepts no callback, opens no network/process boundary, starts no Effect
Lease and cannot authorize replay.  A later packet may consume this receipt as
one prerequisite for a guarded loader and broker integration, but must still
provide the actual executable-byte and runtime/effect authority checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.gates.repository_head_revision import RepositoryHeadRevisionReceipt
from daedalus.runtimes.provider_executable_structure import (
    ProviderExecutableStructureReceipt,
)
from daedalus.runtimes.provider_invocation_resolution import (
    ProviderInvocationResolutionReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence import (
    ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
)
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha

_SCHEMA = "daedalus-provider-executable-pre-admission/1"
_DIGEST_FIELDS = (
    "resolution_sha256",
    "verification_sha256",
    "structure_sha256",
    "completed_retention_sha256",
    "retention_effect_terminal_sha256",
    "repository_head_sha256",
    "invocation_authority_sha256",
    "invocation_contract_sha256",
    "invocation_subject_sha256",
    "invocation_identity_projection_sha256",
    "identity_registry_sha256",
    "identity_descriptor_sha256",
    "target_authority_sha256",
    "target_projection_sha256",
    "target_manifest_sha256",
    "target_descriptor_sha256",
    "adapter_artifact_sha256",
    "adapter_config_sha256",
    "lease_sha256",
    "invoke_source_sha256",
    "output_digests_source_sha256",
)
_ID_FIELDS = (
    "provider_id",
    "adapter_id",
    "implementation_id",
    "entrypoint_id",
    "runtime_id",
    "execution_id",
    "idempotency_key",
)
_TRUE_CLAIMS = (
    "invocation_identity_bound",
    "target_verification_bound",
    "retained_receipt_bound",
    "retention_effect_completed",
    "repository_head_bound",
    "source_revision_verified_against_git_head",
    "broker_binding_prerequisites_composed",
)
_FALSE_CLAIMS = (
    "repository_bytes_executed",
    "provider_execution_allowed",
    "automatic_reexecution_allowed",
    "callback_seam_removed",
    "broker_invocation_performed",
    "effect_start_authorized",
    "owner_approval_issued",
    "promotion_authorized",
    "gate_transition_authorized",
    "closed",
)


class ProviderExecutablePreAdmissionError(RuntimeError):
    """Base class for provider executable pre-admission refusal."""


class ProviderExecutablePreAdmissionShapeError(ProviderExecutablePreAdmissionError):
    """An input or receipt is malformed or has a non-exact type."""


class ProviderExecutablePreAdmissionBindingError(ProviderExecutablePreAdmissionError):
    """Canonical evidence receipts describe different execution subjects."""


def _target(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 4096:
        raise ProviderExecutablePreAdmissionShapeError(
            f"{label} must be a bounded exact target string"
        )
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ProviderExecutablePreAdmissionShapeError(
            f"{label} contains a forbidden character"
        )
    return value


def _canonical_roundtrip(value: Any, expected: type, label: str) -> None:
    if type(value) is not expected:
        raise ProviderExecutablePreAdmissionShapeError(
            f"{label} must be exact {expected.__name__}"
        )
    try:
        payload = value.to_dict()
        rebuilt = expected.from_dict(payload)
    except Exception as exc:  # the component type owns its detailed validation
        raise ProviderExecutablePreAdmissionBindingError(
            f"{label} is not canonical"
        ) from exc
    if rebuilt != value:
        raise ProviderExecutablePreAdmissionBindingError(
            f"{label} changed during canonical reconstruction"
        )


def _identity_projection_sha(
    resolution: ProviderInvocationResolutionReceipt,
) -> str:
    """Rebuild the identity projection digest carried by target evidence."""

    return canonical_sha(
        {
            "schema": "daedalus-provider-invocation-identity/1",
            "provider_id": resolution.provider_id,
            "adapter_id": resolution.adapter_id,
            "implementation_id": resolution.implementation_id,
            "entrypoint_id": resolution.entrypoint_id,
            "runtime_id": resolution.runtime_id,
            "execution_id": resolution.execution_id,
            "idempotency_key": resolution.idempotency_key,
            "source_revision": resolution.source_revision,
            "authority_sha256": resolution.authority_sha256,
            "observation_authority_sha256": (
                resolution.observation_authority_sha256
            ),
            "invocation_contract_sha256": resolution.invocation_contract_sha256,
            "invocation_subject_sha256": resolution.invocation_subject_sha256,
            "registry_sha256": resolution.registry_sha256,
            "descriptor_sha256": resolution.descriptor_sha256,
            "execution_request_sha256": resolution.execution_request_sha256,
            "lease_sha256": resolution.lease_sha256,
            "adapter_artifact_sha256": resolution.adapter_artifact_sha256,
            "adapter_config_sha256": resolution.adapter_config_sha256,
            "runtime_effect_authorized": False,
            "provider_execution_allowed": False,
        }
    )


def _mismatches(comparisons: Mapping[str, tuple[Any, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            field
            for field, (left, right) in comparisons.items()
            if left != right
        )
    )


def _require_same(label: str, comparisons: Mapping[str, tuple[Any, Any]]) -> None:
    mismatch = _mismatches(comparisons)
    if mismatch:
        raise ProviderExecutablePreAdmissionBindingError(
            f"{label} mismatch: " + ", ".join(mismatch)
        )


@dataclass(frozen=True)
class ProviderExecutablePreAdmissionReceipt:
    """Non-executing composition of all evidence needed before guarded loading."""

    source_revision: str
    resolution_sha256: str
    verification_sha256: str
    structure_sha256: str
    completed_retention_sha256: str
    retention_effect_terminal_sha256: str
    repository_head_sha256: str
    provider_id: str
    adapter_id: str
    implementation_id: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    invocation_authority_sha256: str
    invocation_contract_sha256: str
    invocation_subject_sha256: str
    invocation_identity_projection_sha256: str
    identity_registry_sha256: str
    identity_descriptor_sha256: str
    target_authority_sha256: str
    target_projection_sha256: str
    target_manifest_sha256: str
    target_descriptor_sha256: str
    adapter_artifact_sha256: str
    adapter_config_sha256: str
    lease_sha256: str
    invoke_target: str
    invoke_source_sha256: str
    output_digests_target: str
    output_digests_source_sha256: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in _ID_FIELDS:
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            for field in _DIGEST_FIELDS:
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "invoke_target",
                _target(self.invoke_target, "invoke_target"),
            )
            object.__setattr__(
                self,
                "output_digests_target",
                _target(self.output_digests_target, "output_digests_target"),
            )
        except ProviderExecutablePreAdmissionError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderExecutablePreAdmissionShapeError(
                "provider executable pre-admission receipt is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "source_revision": self.source_revision,
            "resolution_sha256": self.resolution_sha256,
            "verification_sha256": self.verification_sha256,
            "structure_sha256": self.structure_sha256,
            "completed_retention_sha256": self.completed_retention_sha256,
            "retention_effect_terminal_sha256": (
                self.retention_effect_terminal_sha256
            ),
            "repository_head_sha256": self.repository_head_sha256,
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "implementation_id": self.implementation_id,
            "entrypoint_id": self.entrypoint_id,
            "runtime_id": self.runtime_id,
            "execution_id": self.execution_id,
            "idempotency_key": self.idempotency_key,
            "invocation_authority_sha256": self.invocation_authority_sha256,
            "invocation_contract_sha256": self.invocation_contract_sha256,
            "invocation_subject_sha256": self.invocation_subject_sha256,
            "invocation_identity_projection_sha256": (
                self.invocation_identity_projection_sha256
            ),
            "identity_registry_sha256": self.identity_registry_sha256,
            "identity_descriptor_sha256": self.identity_descriptor_sha256,
            "target_authority_sha256": self.target_authority_sha256,
            "target_projection_sha256": self.target_projection_sha256,
            "target_manifest_sha256": self.target_manifest_sha256,
            "target_descriptor_sha256": self.target_descriptor_sha256,
            "adapter_artifact_sha256": self.adapter_artifact_sha256,
            "adapter_config_sha256": self.adapter_config_sha256,
            "lease_sha256": self.lease_sha256,
            "invoke_target": self.invoke_target,
            "invoke_source_sha256": self.invoke_source_sha256,
            "output_digests_target": self.output_digests_target,
            "output_digests_source_sha256": self.output_digests_source_sha256,
            **{field: True for field in _TRUE_CLAIMS},
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderExecutablePreAdmissionReceipt":
        fields = {
            "source_revision",
            *_DIGEST_FIELDS,
            *_ID_FIELDS,
            "invoke_target",
            "output_digests_target",
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *_TRUE_CLAIMS,
            *_FALSE_CLAIMS,
        }:
            raise ProviderExecutablePreAdmissionShapeError(
                "provider executable pre-admission fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderExecutablePreAdmissionShapeError(
                "provider executable pre-admission schema is wrong"
            )
        for field in _TRUE_CLAIMS:
            if payload[field] is not True:
                raise ProviderExecutablePreAdmissionShapeError(
                    f"provider executable pre-admission lost claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderExecutablePreAdmissionShapeError(
                    f"provider executable pre-admission escalated claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderExecutablePreAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderExecutablePreAdmissionShapeError(
                "provider executable pre-admission receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_provider_executable_pre_admission(
    resolution: ProviderInvocationResolutionReceipt,
    verification: ProviderExecutableTargetVerificationReceipt,
    structure: ProviderExecutableStructureReceipt,
    completed_retention: ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
    retention_effect_terminal: (
        ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt
    ),
    repository_head: RepositoryHeadRevisionReceipt,
) -> ProviderExecutablePreAdmissionReceipt:
    """Compose fail-closed provider evidence without importing or executing code."""

    components = (
        (resolution, ProviderInvocationResolutionReceipt, "resolution"),
        (
            verification,
            ProviderExecutableTargetVerificationReceipt,
            "verification",
        ),
        (structure, ProviderExecutableStructureReceipt, "structure"),
        (
            completed_retention,
            ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
            "completed_retention",
        ),
        (
            retention_effect_terminal,
            ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt,
            "retention_effect_terminal",
        ),
        (repository_head, RepositoryHeadRevisionReceipt, "repository_head"),
    )
    for value, expected, label in components:
        _canonical_roundtrip(value, expected, label)

    revision = resolution.source_revision
    _require_same(
        "source revision",
        {
            "verification": (verification.source_revision, revision),
            "structure": (structure.source_revision, revision),
            "completed_retention": (completed_retention.source_revision, revision),
            "retention_effect_terminal": (
                retention_effect_terminal.source_revision,
                revision,
            ),
            "repository_head.expected": (
                repository_head.expected_revision,
                revision,
            ),
            "repository_head.resolved": (
                repository_head.resolved_revision,
                revision,
            ),
        },
    )

    verification_sha = verification.digest
    _require_same(
        "retained provider target receipt",
        {
            "completed_retention.provider_target_receipt_sha256": (
                completed_retention.provider_target_receipt_sha256,
                verification_sha,
            ),
            "retention_effect_terminal.provider_target_receipt_sha256": (
                retention_effect_terminal.provider_target_receipt_sha256,
                verification_sha,
            ),
            "retention_effect_terminal.completed_evidence_sha256": (
                retention_effect_terminal.completed_evidence_sha256,
                completed_retention.digest,
            ),
            "retention_effect_terminal.start_receipt_sha256": (
                retention_effect_terminal.start_receipt_sha256,
                completed_retention.start_receipt_sha256,
            ),
            "retention_effect_terminal.terminal_receipt_sha256": (
                retention_effect_terminal.terminal_receipt_sha256,
                completed_retention.terminal_receipt_sha256,
            ),
        },
    )

    common = {
        "provider_id": structure.provider_id,
        "adapter_id": structure.adapter_id,
        "implementation_id": structure.implementation_id,
        "entrypoint_id": structure.entrypoint_id,
        "runtime_id": structure.runtime_id,
        "execution_id": structure.execution_id,
        "idempotency_key": structure.idempotency_key,
        "lease_sha256": structure.lease_sha256,
    }
    _require_same(
        "verification/structure identity",
        {
            field: (getattr(verification, field), expected)
            for field, expected in common.items()
        }
        | {
            "target_authority_sha256": (
                verification.target_authority_sha256,
                structure.target_authority_sha256,
            ),
            "target_projection_sha256": (
                verification.target_projection_sha256,
                structure.target_projection_sha256,
            ),
            "target_manifest_sha256": (
                verification.target_manifest_sha256,
                structure.target_manifest_sha256,
            ),
            "target_descriptor_sha256": (
                verification.target_descriptor_sha256,
                structure.target_descriptor_sha256,
            ),
        },
    )

    _require_same(
        "invocation/structure identity",
        {
            field: (getattr(resolution, field), expected)
            for field, expected in common.items()
        }
        | {
            "invocation_authority_sha256": (
                resolution.authority_sha256,
                structure.invocation_authority_sha256,
            ),
            "invocation_contract_sha256": (
                resolution.invocation_contract_sha256,
                structure.invocation_contract_sha256,
            ),
            "identity_registry_sha256": (
                resolution.registry_sha256,
                structure.identity_registry_sha256,
            ),
            "identity_descriptor_sha256": (
                resolution.descriptor_sha256,
                structure.identity_descriptor_sha256,
            ),
            "adapter_artifact_sha256": (
                resolution.adapter_artifact_sha256,
                structure.adapter_artifact_sha256,
            ),
            "adapter_config_sha256": (
                resolution.adapter_config_sha256,
                structure.adapter_config_sha256,
            ),
            "identity_projection_sha256": (
                _identity_projection_sha(resolution),
                structure.identity_sha256,
            ),
        },
    )

    _require_same(
        "invoke target structure",
        {
            "target": (verification.invoke.target, structure.invoke.target),
            "source_path": (
                verification.invoke.repository_path,
                structure.invoke.source_path,
            ),
            "source_sha256": (
                verification.invoke.source_sha256,
                structure.invoke.source_sha256,
            ),
            "source_size": (
                verification.invoke.source_size,
                structure.invoke.source_size,
            ),
            "line": (verification.invoke.line, structure.invoke.line),
            "end_line": (verification.invoke.end_line, structure.invoke.end_line),
        },
    )
    _require_same(
        "output_digests target structure",
        {
            "target": (
                verification.output_digests.target,
                structure.output_digests.target,
            ),
            "source_path": (
                verification.output_digests.repository_path,
                structure.output_digests.source_path,
            ),
            "source_sha256": (
                verification.output_digests.source_sha256,
                structure.output_digests.source_sha256,
            ),
            "source_size": (
                verification.output_digests.source_size,
                structure.output_digests.source_size,
            ),
            "line": (
                verification.output_digests.line,
                structure.output_digests.line,
            ),
            "end_line": (
                verification.output_digests.end_line,
                structure.output_digests.end_line,
            ),
        },
    )

    return ProviderExecutablePreAdmissionReceipt(
        source_revision=revision,
        resolution_sha256=resolution.digest,
        verification_sha256=verification_sha,
        structure_sha256=structure.digest,
        completed_retention_sha256=completed_retention.digest,
        retention_effect_terminal_sha256=retention_effect_terminal.digest,
        repository_head_sha256=repository_head.digest,
        provider_id=structure.provider_id,
        adapter_id=structure.adapter_id,
        implementation_id=structure.implementation_id,
        entrypoint_id=structure.entrypoint_id,
        runtime_id=structure.runtime_id,
        execution_id=structure.execution_id,
        idempotency_key=structure.idempotency_key,
        invocation_authority_sha256=structure.invocation_authority_sha256,
        invocation_contract_sha256=structure.invocation_contract_sha256,
        invocation_subject_sha256=resolution.invocation_subject_sha256,
        invocation_identity_projection_sha256=structure.identity_sha256,
        identity_registry_sha256=structure.identity_registry_sha256,
        identity_descriptor_sha256=structure.identity_descriptor_sha256,
        target_authority_sha256=structure.target_authority_sha256,
        target_projection_sha256=structure.target_projection_sha256,
        target_manifest_sha256=structure.target_manifest_sha256,
        target_descriptor_sha256=structure.target_descriptor_sha256,
        adapter_artifact_sha256=structure.adapter_artifact_sha256,
        adapter_config_sha256=structure.adapter_config_sha256,
        lease_sha256=structure.lease_sha256,
        invoke_target=structure.invoke.target,
        invoke_source_sha256=structure.invoke.source_sha256,
        output_digests_target=structure.output_digests.target,
        output_digests_source_sha256=structure.output_digests.source_sha256,
    )


__all__ = [
    "ProviderExecutablePreAdmissionBindingError",
    "ProviderExecutablePreAdmissionError",
    "ProviderExecutablePreAdmissionReceipt",
    "ProviderExecutablePreAdmissionShapeError",
    "build_provider_executable_pre_admission",
]
