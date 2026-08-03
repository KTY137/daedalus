"""Strict capability facade for non-runtime persisted Effect Leases.

The existing :mod:`daedalus.kernel.effects` module remains the persistence and
validation authority. This additive facade retains stricter construction
invariants for newly migrated production entrypoints while the compatibility
``LeasedEffectAuthorization`` import remains available during the strangler
migration. It never issues leases, performs external effects or weakens the
separate runtime-bound path.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseLedger,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
    verify_effect_lease,
)
from daedalus.schemas import PolicyDecision
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    EntrypointSpec,
    GuardDecision,
)

_POST_START_AUTHORITY_FAILURE_SHA256 = hashlib.sha256(
    b"non-runtime-effect-authority-invalid-after-durable-start"
).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class NonRuntimeEffectAuthorization:
    """Complete non-runtime capability consumed by one effectful entrypoint.

    Runtime-bearing registry rows are deliberately refused here. They must use
    :class:`daedalus.kernel.runtime_effects.RuntimeBoundEffectAuthorization`
    so a generic caller cannot omit live runtime-trust rechecks.

    The facade owns every authoritative timestamp. Production callers cannot
    backdate grant, start, verification or terminalization to keep an expired
    lease usable or to forge lifecycle chronology. Kill-switch generation is
    read from an injected live authority for every boundary; a long-lived
    facade therefore cannot preserve an obsolete generation after revocation.
    The lower-level ledger keeps explicit timestamp and generation parameters
    for deterministic contract and fault tests only.
    """

    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    effect_ledger: EffectLeaseLedger
    lease_keyring: Mapping[str, bytes | str] = field(repr=False)
    guard_decisions: tuple[GuardDecision, ...]
    kill_switch_generation_reader: Callable[[], int] = field(repr=False)
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = field(
        default=REGISTRY_BY_ID,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.lease.runtime_id:
            raise EffectLeaseBindingMismatch(
                "runtime-bearing leases require RuntimeBoundEffectAuthorization"
            )
        if self.request.runtime_manifest_sha256 is not None or (
            self.request.runtime_conformance_sha256 is not None
        ):
            raise EffectLeaseBindingMismatch(
                "non-runtime effect authorization cannot carry runtime evidence"
            )
        if self.lease.request_sha256 != self.request.digest:
            raise EffectLeaseBindingMismatch(
                "effect authorization request does not match its lease"
            )
        if self.lease.policy_decision_sha256 != self.policy_decision.digest:
            raise EffectLeaseBindingMismatch(
                "effect authorization policy does not match its lease"
            )
        if not self.guard_decisions:
            raise EffectLeaseBindingMismatch(
                "effect authorization requires concrete guard decisions"
            )
        if not callable(self.kill_switch_generation_reader):
            raise TypeError("kill_switch_generation_reader must be callable")
        object.__setattr__(self, "guard_decisions", tuple(self.guard_decisions))
        object.__setattr__(
            self,
            "lease_keyring",
            MappingProxyType(dict(self.lease_keyring)),
        )
        # Fail construction early when the authority is malformed, but never
        # cache this value. Every material boundary reads it again.
        self._read_kill_switch_generation()

    def _read_kill_switch_generation(self) -> int:
        value = self.kill_switch_generation_reader()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                "kill-switch generation authority must return a non-negative integer"
            )
        return value

    def _verify_at(self, instant: datetime, generation: int) -> None:
        verify_effect_lease(
            self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.lease_keyring,
            current_kill_switch_generation=generation,
            now=instant,
            registry=self.registry,
        )

    def verify(self) -> None:
        """Authenticate every retained binding at the facade-owned instant."""

        self._verify_at(_utc_now(), self._read_kill_switch_generation())

    def grant(self) -> None:
        """Persist the authenticated lease before any execution may start."""

        instant = _utc_now()
        generation = self._read_kill_switch_generation()
        self._verify_at(instant, generation)
        self.effect_ledger.grant(
            self.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.lease_keyring,
            current_kill_switch_generation=generation,
            granted_at=instant,
            registry=self.registry,
        )

    def begin_effect(
        self,
        execution: EffectExecutionRequest,
    ) -> EffectStartResult:
        """Commit a start receipt before returning ``execute=True``."""

        instant = _utc_now()
        generation = self._read_kill_switch_generation()
        self._verify_at(instant, generation)
        result = self.effect_ledger.begin(
            self.lease,
            execution,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.lease_keyring,
            guard_decisions=self.guard_decisions,
            current_kill_switch_generation=generation,
            started_at=instant,
            registry=self.registry,
        )
        if result.execute:
            try:
                # Close the revocation window between the durable start commit
                # and returning effect authority to the caller.
                self._verify_at(
                    _utc_now(),
                    self._read_kill_switch_generation(),
                )
            except Exception:
                self.effect_ledger.finish(
                    result.receipt,
                    outcome="cancelled",
                    detail_sha256=_POST_START_AUTHORITY_FAILURE_SHA256,
                    finished_at=_utc_now(),
                )
                raise
        return result

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        """Persist one terminal receipt bound to this exact authorization."""

        if start_receipt.lease_sha256 != self.lease.digest:
            raise EffectLeaseBindingMismatch(
                "start receipt belongs to a different effect lease"
            )
        # Revocation must still allow FAILED/CANCELLED bookkeeping, but a
        # successful terminal receipt and its outputs require live authority.
        if isinstance(outcome, str) and outcome.strip().upper() == "COMPLETED":
            self._verify_at(
                _utc_now(),
                self._read_kill_switch_generation(),
            )
        return self.effect_ledger.finish(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
            finished_at=_utc_now(),
        )


__all__ = ["NonRuntimeEffectAuthorization"]
