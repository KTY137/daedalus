"""Pure restart/replay decisions for provider-target receipt retention.

This module consumes one exact, already materialized retention-admission receipt
and emits a deterministic non-executing decision.  It deliberately has no
Effect-Lease ledger, retention ledger, filesystem, process, network, approval,
promotion, or Gate authority.

The projection never turns an observed state into execution authority:

* ``not_started`` requests a separate fresh-start authorization;
* ``started`` requires authenticated external reconciliation and forbids replay;
* terminal states remain terminal and cannot be retried automatically.

An exact dataclass instance is still only a bound input identity.  This module
does not independently repeat the persisted-state or topology verification that
created the admission receipt and therefore records that claim as false.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.runtimes.provider_target_receipt_retention_admission import (
    ProviderTargetReceiptRetentionAdmissionError,
    ProviderTargetReceiptRetentionAdmissionReceipt,
)
from daedalus.schemas import _revision, _sha256
from daedalus.spine.envelope import canonical_sha

_SCHEMA = "daedalus-provider-target-receipt-retention-recovery-decision/1"
_STATE_DECISIONS = {
    "not_started": "request_fresh_start_authorization",
    "started": "manual_reconciliation_required",
    "COMPLETED": "verify_completed_retention_evidence",
    "FAILED": "terminal_failure_refusal",
    "CANCELLED": "terminal_cancellation_refusal",
}
_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class ProviderTargetReceiptRetentionRecoveryError(RuntimeError):
    """Base class for fail-closed recovery-decision refusal."""


class ProviderTargetReceiptRetentionRecoveryShapeError(
    ProviderTargetReceiptRetentionRecoveryError
):
    """A recovery decision or caller input has a malformed shape."""


class ProviderTargetReceiptRetentionRecoveryBindingError(
    ProviderTargetReceiptRetentionRecoveryError
):
    """The exact admission identity, revision, or state binding disagrees."""


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionRecoveryDecision:
    """Canonical non-authorizing decision for one persisted retention state."""

    source_revision: str
    admission_sha256: str
    execution_state: str
    decision: str
    start_receipt_sha256: str | None
    terminal_receipt_sha256: str | None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "admission_sha256",
                _sha256(self.admission_sha256, "admission_sha256"),
            )
            for field in ("start_receipt_sha256", "terminal_receipt_sha256"):
                value = getattr(self, field)
                if value is not None:
                    object.__setattr__(self, field, _sha256(value, field))
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery decision is malformed"
            ) from exc

        if type(self.execution_state) is not str or (
            self.execution_state not in _STATE_DECISIONS
        ):
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery execution_state is unknown"
            )
        expected_decision = _STATE_DECISIONS[self.execution_state]
        if type(self.decision) is not str or self.decision != expected_decision:
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery decision is detached from execution_state"
            )
        if self.execution_state == "not_started":
            if (
                self.start_receipt_sha256 is not None
                or self.terminal_receipt_sha256 is not None
            ):
                raise ProviderTargetReceiptRetentionRecoveryShapeError(
                    "not_started recovery cannot retain execution receipts"
                )
        elif self.execution_state == "started":
            if (
                self.start_receipt_sha256 is None
                or self.terminal_receipt_sha256 is not None
            ):
                raise ProviderTargetReceiptRetentionRecoveryShapeError(
                    "started recovery must retain only the start receipt"
                )
        elif (
            self.start_receipt_sha256 is None
            or self.terminal_receipt_sha256 is None
        ):
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "terminal recovery must retain start and terminal receipts"
            )

    def to_dict(self) -> dict[str, Any]:
        terminal = self.execution_state in _TERMINAL_STATES
        reconciliation = self.execution_state == "started"
        return {
            "schema": _SCHEMA,
            "source_revision": self.source_revision,
            "admission_sha256": self.admission_sha256,
            "execution_state": self.execution_state,
            "decision": self.decision,
            "start_receipt_sha256": self.start_receipt_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
            "admission_identity_bound": True,
            "persisted_state_reverified": False,
            "manual_reconciliation_required": reconciliation,
            "terminal_state_observed": terminal,
            "automatic_reexecution_allowed": False,
            "effect_start_authorized": False,
            "retention_write_authorized": False,
            "effect_terminalization_authorized": False,
            "canonical_entrypoint_registered": False,
            "gate_transition_authorized": False,
            "closed": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionRecoveryDecision":
        fields = {
            "source_revision",
            "admission_sha256",
            "execution_state",
            "decision",
            "start_receipt_sha256",
            "terminal_receipt_sha256",
        }
        claims = {
            "admission_identity_bound",
            "persisted_state_reverified",
            "manual_reconciliation_required",
            "terminal_state_observed",
            "automatic_reexecution_allowed",
            "effect_start_authorized",
            "retention_write_authorized",
            "effect_terminalization_authorized",
            "canonical_entrypoint_registered",
            "gate_transition_authorized",
            "closed",
        }
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema",
            *fields,
            *claims,
        }:
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery decision fields are not exact"
            )
        if payload["schema"] != _SCHEMA:
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery decision schema is wrong"
            )
        state = payload["execution_state"]
        if type(state) is not str or state not in _STATE_DECISIONS:
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery execution_state is unknown"
            )
        expected_claims = {
            "admission_identity_bound": True,
            "persisted_state_reverified": False,
            "manual_reconciliation_required": state == "started",
            "terminal_state_observed": state in _TERMINAL_STATES,
            "automatic_reexecution_allowed": False,
            "effect_start_authorized": False,
            "retention_write_authorized": False,
            "effect_terminalization_authorized": False,
            "canonical_entrypoint_registered": False,
            "gate_transition_authorized": False,
            "closed": False,
        }
        for field, expected in expected_claims.items():
            if payload[field] is not expected:
                raise ProviderTargetReceiptRetentionRecoveryShapeError(
                    f"retention recovery decision contains unsupported claim: {field}"
                )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionRecoveryError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionRecoveryShapeError(
                "retention recovery decision is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def decide_provider_target_receipt_retention_recovery(
    admission: ProviderTargetReceiptRetentionAdmissionReceipt,
    *,
    expected_source_revision: str,
) -> ProviderTargetReceiptRetentionRecoveryDecision:
    """Derive a pure fail-closed restart decision from one exact admission.

    The function performs no state read and grants no capability.  Callers must
    separately re-run admission and obtain the appropriate fresh authority at
    the future effectful boundary.
    """

    if type(admission) is not ProviderTargetReceiptRetentionAdmissionReceipt:
        raise ProviderTargetReceiptRetentionRecoveryShapeError(
            "admission must be exact ProviderTargetReceiptRetentionAdmissionReceipt"
        )
    try:
        revision = _revision(expected_source_revision, "expected_source_revision")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionRecoveryShapeError(
            "expected_source_revision is malformed"
        ) from exc
    if admission.source_revision != revision:
        raise ProviderTargetReceiptRetentionRecoveryBindingError(
            "retention admission belongs to a stale source revision"
        )

    try:
        snapshot = admission.to_dict()
        restored = ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(snapshot)
    except ProviderTargetReceiptRetentionAdmissionError as exc:
        raise ProviderTargetReceiptRetentionRecoveryBindingError(
            "retention admission does not reconstruct canonically"
        ) from exc
    if restored != admission:
        raise ProviderTargetReceiptRetentionRecoveryBindingError(
            "retention admission reconstruction changed its subject"
        )

    admission_digest = admission.digest
    state = admission.execution_state
    result = ProviderTargetReceiptRetentionRecoveryDecision(
        source_revision=revision,
        admission_sha256=admission_digest,
        execution_state=state,
        decision=_STATE_DECISIONS[state],
        start_receipt_sha256=admission.start_receipt_sha256,
        terminal_receipt_sha256=admission.terminal_receipt_sha256,
    )

    try:
        final_snapshot = admission.to_dict()
        final_restored = ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(
            final_snapshot
        )
    except ProviderTargetReceiptRetentionAdmissionError as exc:
        raise ProviderTargetReceiptRetentionRecoveryBindingError(
            "retention admission changed during decision projection"
        ) from exc
    if (
        final_snapshot != snapshot
        or final_restored != restored
        or admission.digest != admission_digest
        or admission.source_revision != revision
        or admission.execution_state != state
        or result.admission_sha256 != admission_digest
    ):
        raise ProviderTargetReceiptRetentionRecoveryBindingError(
            "retention admission changed during decision projection"
        )
    return result


__all__ = [
    "ProviderTargetReceiptRetentionRecoveryBindingError",
    "ProviderTargetReceiptRetentionRecoveryDecision",
    "ProviderTargetReceiptRetentionRecoveryError",
    "ProviderTargetReceiptRetentionRecoveryShapeError",
    "decide_provider_target_receipt_retention_recovery",
]
