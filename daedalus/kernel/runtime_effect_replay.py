"""Read-only replay projection for runtime-bound Effect-Lease executions.

The generic effect replay reader authenticates the inner signed EffectLease and
its persisted execution row. A runtime-bearing execution has a second authority:
``RuntimeBoundEffectLease`` binds the EffectLease to one exact persisted runtime
trust record. This module composes both authorities at the retained start
instant without granting, starting, finishing, revoking, or re-executing an
effect.

The current runtime trust record must still be active and authenticated when the
projection is requested. This conservative rule intentionally refuses historical
runtime capability replay after trust expiry or quarantine until an authenticated
append-only runtime trust history exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    EffectReplayProjectionError,
    PersistedEffectLeaseSubject,
    _project_persisted_execution,
)
from daedalus.kernel.effects import EffectExecutionRequest, _parse_utc
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    RuntimeLeaseAdmissionError,
    verify_runtime_bound_effect_lease,
)
from daedalus.runtimes.trust_store import RuntimeTrustRecord, RuntimeTrustStoreError


class RuntimeEffectReplayProjectionError(EffectReplayProjectionError):
    """Runtime-bound replay material is absent, stale, or unauthenticated."""


@dataclass(frozen=True)
class RuntimeEffectExecutionReplaySnapshot:
    """Exact persisted effect state plus its active runtime-trust subject."""

    execution: EffectExecutionReplaySnapshot
    runtime_trust_record: RuntimeTrustRecord
    verified_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.execution, EffectExecutionReplaySnapshot):
            raise ValueError("execution snapshot type is invalid")
        if not isinstance(self.runtime_trust_record, RuntimeTrustRecord):
            raise ValueError("runtime trust record type is invalid")
        try:
            verified = _parse_utc(self.verified_at, "verified_at")
        except Exception as exc:
            raise ValueError("verified_at must be a timezone-aware timestamp") from exc
        canonical = verified.isoformat(timespec="microseconds")
        if canonical != self.verified_at:
            raise ValueError("verified_at must be canonical UTC microsecond ISO-8601")
        if self.runtime_trust_record.record_sha256 == "0" * 64:
            raise ValueError("runtime trust record identity cannot be null")

    @property
    def pending_reconciliation(self) -> bool:
        return self.execution.pending_reconciliation


def inspect_runtime_effect_execution(
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
) -> RuntimeEffectExecutionReplaySnapshot | None:
    """Project one runtime-bound execution without changing persisted state.

    ``None`` means the exact runtime-bound lease is persisted but the exact
    execution has no durable start. A returned snapshot is either pending
    reconciliation or terminal; neither result grants authority to execute.
    """

    if not isinstance(authorization, RuntimeBoundEffectAuthorization):
        raise TypeError(
            "runtime effect replay requires RuntimeBoundEffectAuthorization"
        )
    if not isinstance(execution, EffectExecutionRequest):
        raise TypeError(
            "runtime effect replay requires EffectExecutionRequest"
        )

    # Reuse the strict read-only persisted EffectLease projection. The subject
    # carries the exact inner lease but no capability: a runtime-bearing lease
    # must never be rewrapped as a NonRuntimeEffectAuthorization, because that
    # facade exists precisely to refuse runtime leases. No live kill-switch
    # reader is needed either; historical verification is evaluated at the
    # retained start instant and the generation recorded in the lease.
    inner = PersistedEffectLeaseSubject(
        lease=authorization.capability.lease,
        request=authorization.request,
        policy_decision=authorization.policy_decision,
        effect_ledger=authorization.effect_ledger,
        lease_keyring=authorization.lease_keyring,
        registry=authorization.registry,
    )
    try:
        effect_snapshot = _project_persisted_execution(inner, execution)
    except EffectReplayProjectionError as exc:
        raise RuntimeEffectReplayProjectionError(
            "inner Effect-Lease replay failed"
        ) from exc
    if effect_snapshot is None:
        return None

    try:
        start_instant = _parse_utc(
            effect_snapshot.start_receipt.started_at,
            "started_at",
        )
        trust_record = verify_runtime_bound_effect_lease(
            authorization.capability,
            request=authorization.request,
            policy_decision=authorization.policy_decision,
            lease_keyring=authorization.lease_keyring,
            runtime_authority_keyring=authorization.runtime_authority_keyring,
            runtime_trust_ledger=authorization.runtime_trust_ledger,
            current_kill_switch_generation=(
                authorization.capability.lease.kill_switch_generation
            ),
            now=start_instant,
            registry=authorization.registry,
        )
    except (RuntimeLeaseAdmissionError, RuntimeTrustStoreError, ValueError) as exc:
        raise RuntimeEffectReplayProjectionError(
            "runtime-bound capability failed historical start verification"
        ) from exc
    if trust_record.record_sha256 != authorization.capability.runtime_trust_record_sha256:
        raise RuntimeEffectReplayProjectionError(
            "runtime trust record differs from the signed capability"
        )
    if trust_record.runtime_id != authorization.capability.runtime_id:
        raise RuntimeEffectReplayProjectionError(
            "runtime trust identity differs from the signed capability"
        )
    return RuntimeEffectExecutionReplaySnapshot(
        execution=effect_snapshot,
        runtime_trust_record=trust_record,
        verified_at=start_instant.isoformat(timespec="microseconds"),
    )


__all__ = [
    "RuntimeEffectExecutionReplaySnapshot",
    "RuntimeEffectReplayProjectionError",
    "inspect_runtime_effect_execution",
]
