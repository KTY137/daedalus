"""Read-only binding of completed retention evidence to persisted Effect state.

This module verifies that one exact completed provider-target receipt-retention
evidence receipt is backed by the exact persisted ``COMPLETED`` Effect-Lease
execution. It performs two query-only replay projections, fences the concrete
Effect-Lease SQLite identity around both reads, and binds the terminal output to
the retained receipt artifact.

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
from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    EffectReplayProjectionError,
    inspect_effect_execution,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceError,
    ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
)
from daedalus.schemas import _revision, _sha256
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


def _require_completed_snapshot(
    snapshot: EffectExecutionReplaySnapshot | None,
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
    if snapshot.terminal_receipt.outcome != "COMPLETED":
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "persisted Effect terminal outcome is not COMPLETED"
        )
    return snapshot.start_receipt, snapshot.terminal_receipt


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

    try:
        authority_revisions = {
            authorization.request.provenance.source_revision,
            authorization.policy_decision.provenance.source_revision,
            authorization.lease.provenance.source_revision,
        }
        effect_store_path = Path(authorization.effect_ledger.path)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(
            "retention authorization is malformed"
        ) from exc
    if authority_revisions != {revision}:
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "retention Effect authority belongs to a stale source revision"
        )

    store_before = _effect_store_identity(effect_store_path)
    try:
        first = inspect_effect_execution(authorization, execution)
    except EffectReplayProjectionError as exc:
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
    except EffectReplayProjectionError as exc:
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

    start, terminal = _require_completed_snapshot(second)
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
    if (
        final_payload != completed_payload
        or final_restored != restored_completed
        or completed_evidence.digest != canonical_sha(completed_payload)
    ):
        raise ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError(
            "completed retention evidence changed during Effect replay verification"
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
