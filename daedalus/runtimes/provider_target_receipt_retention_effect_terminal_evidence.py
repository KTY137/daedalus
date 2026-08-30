# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Read-only binding of completed retention evidence to persisted Effect state.

This module verifies that one exact completed provider-target receipt-retention
evidence receipt is backed by the exact persisted ``COMPLETED`` Effect-Lease
execution. It performs two query-only replay projections, fences the concrete
Effect-Lease SQLite identity around both reads, independently rebuilds the
persisted receipt bindings, and binds the terminal output to the retained
receipt artifact.

The receipt emitted here is evidence only. It cannot start, repeat or finish an
effect, register an entrypoint, promote a candidate, issue OwnerApproval, or
close Gate 0.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    EffectReplayProjectionError,
    inspect_effect_execution,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseError,
    EffectLeaseLedger,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceError,
    ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_ENTRYPOINT,
)
from daedalus.schemas import PolicyDecision, _revision, _sha256
from daedalus.spine.envelope import canonical_sha

_SCHEMA = "daedalus-provider-target-receipt-retention-effect-terminal-evidence/1"
_DIGEST_FIELDS = (
    "completed_evidence_sha256",
    "provider_target_receipt_sha256",
    "retention_execution_request_sha256",
    "retention_effect_lease_sha256",
    "start_receipt_sha256",
    "terminal_receipt_sha256",
    "terminal_output_set_sha256",
    "effect_execution_evidence_sha256",
    "effect_lease_store_identity_sha256",
)
_FALSE_CLAIMS = (
    "automatic_reexecution_allowed",
    "effect_start_authorized",
    "retention_write_authorized",
    "effect_terminalization_authorized",
    "canonical_entrypoint_registered",
    "owner_approval_issued",
    "promotion_authorized",
    "gate_transition_authorized",
    "closed",
)


class ProviderTargetReceiptRetentionEffectTerminalEvidenceError(RuntimeError):
    """Base class for persisted Effect-terminal evidence refusal."""


class ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
    ProviderTargetReceiptRetentionEffectTerminalEvidenceError
):
    """A caller supplied a malformed or non-exact evidence subject."""


class ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
    ProviderTargetReceiptRetentionEffectTerminalEvidenceError
):
    """Completed retention evidence and persisted Effect state disagree."""


def _commit_revision(value: Any, label: str) -> str:
    try:
        revision = _revision(value, label)
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            f"{label} is malformed"
        ) from exc
    if len(revision) != 40:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            f"{label} must be an exact 40-hex commit revision"
        )
    return revision


def _canonical_time(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 128:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            f"{label} must be a bounded exact timestamp string"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            f"{label} is malformed"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            f"{label} must be timezone-aware"
        )
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if canonical != value:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            f"{label} must be canonical UTC ISO-8601"
        )
    return canonical


def _bounded_path(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
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


def _effect_store_identity(path: Path) -> dict[str, Any]:
    try:
        absolute = Path(os.path.abspath(os.fspath(path)))
        if _contains_symlink(absolute):
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
                "Effect-Lease store path must not contain symlinks"
            )
        resolved = absolute.resolve(strict=True)
        info = resolved.stat()
    except ProviderTargetReceiptRetentionEffectTerminalEvidenceError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "Effect-Lease store cannot be resolved"
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "Effect-Lease store must be a real regular file"
        )
    if info.st_nlink != 1:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "Effect-Lease store must have one filesystem identity"
        )
    return {
        "path": os.fspath(resolved),
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
    }


def _canonical_completed(
    evidence: ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
) -> tuple[dict[str, Any], ProviderTargetReceiptRetentionCompletedEvidenceReceipt]:
    try:
        payload = evidence.to_dict()
        restored = ProviderTargetReceiptRetentionCompletedEvidenceReceipt.from_dict(
            payload
        )
    except ProviderTargetReceiptRetentionCompletedEvidenceError as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "completed retention evidence is noncanonical"
        ) from exc
    if restored != evidence:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "completed retention evidence changed during reconstruction"
        )
    return payload, restored


def _authority_snapshot(
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    revision: str,
) -> tuple[dict[str, str], Path]:
    exact = (
        (authorization.lease, EffectLease, "authorization.lease"),
        (authorization.request, EffectLeaseRequest, "authorization.request"),
        (
            authorization.policy_decision,
            PolicyDecision,
            "authorization.policy_decision",
        ),
        (
            authorization.effect_ledger,
            EffectLeaseLedger,
            "authorization.effect_ledger",
        ),
    )
    for value, expected, label in exact:
        if type(value) is not expected:
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                f"{label} must be exact {expected.__name__}"
            )

    request = authorization.request
    policy = authorization.policy_decision
    lease = authorization.lease
    if (
        request.entrypoint_id != RETENTION_ENTRYPOINT
        or lease.entrypoint_id != RETENTION_ENTRYPOINT
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect authority names the wrong retention entrypoint"
        )
    if (
        lease.request_id != request.request_id
        or lease.request_sha256 != request.digest
        or lease.policy_decision_id != policy.decision_id
        or lease.policy_decision_sha256 != policy.digest
        or policy.subject_id != request.request_id
        or policy.subject_sha256 != request.digest
        or policy.verdict != "allow"
        or lease.requested_effects != request.requested_effects
        or lease.effect_scope != request.effect_scope
        or policy.effect_scope != request.effect_scope
        or lease.idempotency_namespace != request.idempotency_namespace
        or lease.kill_switch_generation != request.kill_switch_generation
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect authority components are detached"
        )
    if (
        request.runtime_manifest_sha256 is not None
        or request.runtime_conformance_sha256 is not None
        or lease.runtime_id
        or lease.runtime_manifest_sha256 is not None
        or lease.runtime_conformance_sha256 is not None
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "receipt retention requires a non-runtime Effect authority"
        )

    authority_revisions = {
        request.provenance.source_revision,
        policy.provenance.source_revision,
        lease.provenance.source_revision,
    }
    if authority_revisions != {revision}:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "retention Effect authority belongs to a stale source revision"
        )

    if (
        execution.requested_effects != lease.requested_effects
        or execution.writable_paths != lease.effect_scope.writable_paths
        or execution.egress_endpoints
        or execution.tools
        or execution.secret_refs
        or execution.max_cost_microusd != 0
        or execution.kill_switch_ref != lease.effect_scope.kill_switch_ref
        or execution.kill_switch_generation != lease.kill_switch_generation
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "retention execution is detached from the exact leased effect scope"
        )

    try:
        store_path = Path(authorization.effect_ledger.path)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            "retention Effect-Lease store path is malformed"
        ) from exc
    return (
        {
            "request_sha256": request.digest,
            "policy_decision_sha256": policy.digest,
            "lease_sha256": lease.digest,
            "execution_request_sha256": execution.digest,
        },
        store_path,
    )


def _require_completed_snapshot(
    snapshot: EffectExecutionReplaySnapshot | None,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
) -> tuple[LeasedEffectStartReceipt, EffectTerminalReceipt]:
    if type(snapshot) is not EffectExecutionReplaySnapshot:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect execution is absent or non-exact"
        )
    if snapshot.state != "COMPLETED":
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect execution is not COMPLETED"
        )
    if type(snapshot.start_receipt) is not LeasedEffectStartReceipt:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect start receipt is non-exact"
        )
    if type(snapshot.terminal_receipt) is not EffectTerminalReceipt:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal receipt is absent or non-exact"
        )

    start = snapshot.start_receipt
    terminal = snapshot.terminal_receipt
    try:
        start_receipt_sha = _sha256(start.receipt_sha256, "start.receipt_sha256")
        boundary_sha = _sha256(
            start.boundary_receipt_sha256,
            "start.boundary_receipt_sha256",
        )
        terminal_receipt_sha = _sha256(
            terminal.receipt_sha256,
            "terminal.receipt_sha256",
        )
        terminal_start_sha = _sha256(
            terminal.start_receipt_sha256,
            "terminal.start_receipt_sha256",
        )
        outputs = tuple(
            _sha256(value, f"terminal.output_digests[{index}]")
            for index, value in enumerate(terminal.output_digests)
        )
        detail = (
            None
            if terminal.detail_sha256 is None
            else _sha256(terminal.detail_sha256, "terminal.detail_sha256")
        )
        started_at = _canonical_time(start.started_at, "start.started_at")
        finished_at = _canonical_time(terminal.finished_at, "terminal.finished_at")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect receipts are malformed"
        ) from exc

    if tuple(sorted(set(outputs))) != outputs:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal outputs are not sorted and unique"
        )
    if (
        start.lease_sha256 != authorization.lease.digest
        or start.execution_id != execution.execution_id
        or start.idempotency_key != execution.idempotency_key
        or start.execution_request_sha256 != execution.digest
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect start receipt is detached from authority or execution"
        )
    expected_start_sha = canonical_sha(
        {
            "lease_sha256": authorization.lease.digest,
            "execution_id": execution.execution_id,
            "idempotency_key": execution.idempotency_key,
            "execution_request_sha256": execution.digest,
            "boundary_receipt_sha256": boundary_sha,
            "started_at": started_at,
        }
    )
    if start_receipt_sha != expected_start_sha:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect start receipt digest is invalid"
        )

    if (
        terminal.outcome != "COMPLETED"
        or terminal.lease_sha256 != authorization.lease.digest
        or terminal.execution_id != execution.execution_id
        or terminal_start_sha != start_receipt_sha
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal receipt is detached from its start"
        )
    if datetime.fromisoformat(finished_at) < datetime.fromisoformat(started_at):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal receipt precedes its start"
        )
    expected_terminal_sha = canonical_sha(
        {
            "lease_sha256": authorization.lease.digest,
            "execution_id": execution.execution_id,
            "start_receipt_sha256": start_receipt_sha,
            "outcome": "COMPLETED",
            "output_digests": list(outputs),
            "detail_sha256": detail,
            "finished_at": finished_at,
        }
    )
    if terminal_receipt_sha != expected_terminal_sha:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal receipt digest is invalid"
        )
    return start, terminal


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt:
    """Canonical non-authorizing proof of one persisted completed Effect."""

    source_revision: str
    completed_evidence_sha256: str
    provider_target_receipt_sha256: str
    retention_execution_request_sha256: str
    retention_effect_lease_sha256: str
    start_receipt_sha256: str
    terminal_receipt_sha256: str
    terminal_output_set_sha256: str
    effect_execution_evidence_sha256: str
    effect_lease_store_identity_sha256: str
    effect_lease_store_path: str
    terminal_finished_at: str

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
                "effect_lease_store_path",
                _bounded_path(
                    self.effect_lease_store_path,
                    "effect_lease_store_path",
                ),
            )
            object.__setattr__(
                self,
                "terminal_finished_at",
                _canonical_time(self.terminal_finished_at, "terminal_finished_at"),
            )
        except ProviderTargetReceiptRetentionEffectTerminalEvidenceError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                "Effect-terminal evidence receipt is malformed"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "source_revision": self.source_revision,
            "completed_evidence_sha256": self.completed_evidence_sha256,
            "provider_target_receipt_sha256": self.provider_target_receipt_sha256,
            "retention_execution_request_sha256": (
                self.retention_execution_request_sha256
            ),
            "retention_effect_lease_sha256": self.retention_effect_lease_sha256,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "terminal_output_set_sha256": self.terminal_output_set_sha256,
            "effect_execution_evidence_sha256": (
                self.effect_execution_evidence_sha256
            ),
            "effect_lease_store_identity_sha256": (
                self.effect_lease_store_identity_sha256
            ),
            "effect_lease_store_path": self.effect_lease_store_path,
            "terminal_finished_at": self.terminal_finished_at,
            "completed_retention_evidence_bound": True,
            "persisted_effect_terminal_verified": True,
            "exact_execution_request_bound": True,
            "exact_effect_lease_bound": True,
            "retained_receipt_output_bound": True,
            "effect_lease_store_stable": True,
            **{field: False for field in _FALSE_CLAIMS},
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt":
        fields = {
            "source_revision",
            *_DIGEST_FIELDS,
            "effect_lease_store_path",
            "terminal_finished_at",
        }
        true_claims = {
            "completed_retention_evidence_bound",
            "persisted_effect_terminal_verified",
            "exact_execution_request_bound",
            "exact_effect_lease_bound",
            "retained_receipt_output_bound",
            "effect_lease_store_stable",
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *true_claims,
            *_FALSE_CLAIMS,
        }:
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                "Effect-terminal evidence fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                "Effect-terminal evidence schema is wrong"
            )
        for field in true_claims:
            if payload[field] is not True:
                raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                    f"Effect-terminal evidence lost required claim: {field}"
                )
        for field in _FALSE_CLAIMS:
            if payload[field] is not False:
                raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                    f"Effect-terminal evidence contains unsupported claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionEffectTerminalEvidenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                "Effect-terminal evidence receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def verify_provider_target_receipt_retention_effect_terminal_evidence(
    completed_evidence: ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    *,
    expected_source_revision: str,
) -> ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt:
    """Bind completed retention evidence to the exact persisted Effect terminal."""

    exact = (
        (
            completed_evidence,
            ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
            "completed_evidence",
        ),
        (
            authorization,
            NonRuntimeEffectAuthorization,
            "authorization",
        ),
        (execution, EffectExecutionRequest, "execution"),
    )
    for value, expected, label in exact:
        if type(value) is not expected:
            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
                f"{label} must be exact {expected.__name__}"
            )

    revision = _commit_revision(
        expected_source_revision,
        "expected_source_revision",
    )
    completed_payload, restored_completed = _canonical_completed(completed_evidence)
    if completed_evidence.source_revision != revision:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "completed retention evidence belongs to a stale source revision"
        )

    authority_before, effect_store_path = _authority_snapshot(
        authorization,
        execution,
        revision,
    )
    store_before = _effect_store_identity(effect_store_path)
    try:
        first = inspect_effect_execution(authorization, execution)
    except (EffectReplayProjectionError, EffectLeaseError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect execution did not verify"
        ) from exc
    store_mid = _effect_store_identity(effect_store_path)
    if store_mid != store_before:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "Effect-Lease store changed during the first replay projection"
        )
    try:
        second = inspect_effect_execution(authorization, execution)
    except (EffectReplayProjectionError, EffectLeaseError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect execution did not verify on replay"
        ) from exc
    store_after = _effect_store_identity(effect_store_path)
    if store_after != store_before:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "Effect-Lease store changed during replay verification"
        )
    if first != second:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect execution changed between read-only projections"
        )

    start, terminal = _require_completed_snapshot(
        second,
        authorization,
        execution,
    )
    if start.receipt_sha256 != completed_evidence.start_receipt_sha256:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect start receipt is detached from completed evidence"
        )
    if terminal.receipt_sha256 != completed_evidence.terminal_receipt_sha256:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal receipt is detached from completed evidence"
        )
    if terminal.output_digests != (
        completed_evidence.receipt_artifact_sha256,
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal output is detached from the retained receipt"
        )

    final_payload, final_restored = _canonical_completed(completed_evidence)
    authority_after, final_effect_store_path = _authority_snapshot(
        authorization,
        execution,
        revision,
    )
    if (
        final_payload != completed_payload
        or final_restored != restored_completed
        or completed_evidence.digest != canonical_sha(completed_payload)
        or authority_after != authority_before
        or final_effect_store_path != effect_store_path
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "completed evidence or Effect authority changed during replay verification"
        )

    execution_evidence = canonical_sha(
        {
            "state": second.state,
            "execution_request_sha256": execution.digest,
            "lease_sha256": authorization.lease.digest,
            "start_receipt": start.to_dict(),
            "terminal_receipt": terminal.to_dict(),
        }
    )
    output_set = canonical_sha(
        {"output_digests": list(terminal.output_digests)}
    )
    store_identity = canonical_sha(store_after)
    return ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt(
        source_revision=revision,
        completed_evidence_sha256=completed_evidence.digest,
        provider_target_receipt_sha256=(
            completed_evidence.provider_target_receipt_sha256
        ),
        retention_execution_request_sha256=execution.digest,
        retention_effect_lease_sha256=authorization.lease.digest,
        start_receipt_sha256=start.receipt_sha256,
        terminal_receipt_sha256=terminal.receipt_sha256,
        terminal_output_set_sha256=output_set,
        effect_execution_evidence_sha256=execution_evidence,
        effect_lease_store_identity_sha256=store_identity,
        effect_lease_store_path=store_after["path"],
        terminal_finished_at=terminal.finished_at,
    )


__all__ = [
    "ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError",
    "ProviderTargetReceiptRetentionEffectTerminalEvidenceError",
    "ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt",
    "ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError",
    "verify_provider_target_receipt_retention_effect_terminal_evidence",
]
