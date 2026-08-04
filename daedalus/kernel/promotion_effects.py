"""Typed Effect-Lease composition for the sealed promotion boundary.

This module is deliberately not a promotion implementation and does not issue an
Effect Lease.  It composes three existing authorities without replacing any of
them:

* :class:`PromotionAuthorization` names the exact owner-approved candidate,
  evidence, source revision and live target revision;
* :class:`NonRuntimeEffectAuthorization` authenticates and persists the bounded
  non-runtime Effect Lease;
* :class:`EffectExecutionRequest` narrows that lease to one idempotent promotion
  execution.

The live Kairos seam is migrated in a later Work Packet.  Until that wiring is
installed, the canonical registry row remains ``local_guards`` and no caller can
construct a valid production capability from the canonical registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Wiring,
)
from daedalus.spine.envelope import canonical_sha


PROMOTION_ENTRYPOINT_ID = "python.promote_candidates"
PROMOTION_TARGET = "daedalus.kairos.gated_writes:promote_candidates"
PROMOTION_EFFECTS = tuple(
    sorted(
        (
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.REPOSITORY_MUTATION.value,
        )
    )
)
PROMOTION_GUARD_CONTRACTS = tuple(
    sorted(
        (
            "containment.worktree",
            "promotion.owner_approval",
            "spine.intent_ledger",
        )
    )
)


class PromotionEffectBindingMismatch(RuntimeError):
    """The supplied lease/execution authority names another promotion subject."""


def _promotion_authorization_digest(value: PromotionAuthorization) -> str:
    if not isinstance(value, PromotionAuthorization):
        raise PromotionEffectBindingMismatch(
            "promotion effect capability requires PromotionAuthorization"
        )
    body = {
        "promotion_id": value.promotion_id,
        "candidate_artifact_sha256": value.candidate_artifact_sha256,
        "evidence_packet_sha256": value.evidence_packet_sha256,
        "source_revision": value.source_revision,
        "target_ref": value.target_ref,
        "live_target_revision": value.live_target_revision,
        "approval_consumption_sha256": value.approval_consumption_sha256,
    }
    digest = canonical_sha(body)
    if digest != value.authorization_sha256:
        raise PromotionEffectBindingMismatch(
            "promotion authorization digest does not bind its fields"
        )
    return digest


def _registry_row(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> EntrypointSpec:
    if isinstance(registry, Mapping):
        row = registry.get(PROMOTION_ENTRYPOINT_ID)
        if row is None or row.id != PROMOTION_ENTRYPOINT_ID:
            raise PromotionEffectBindingMismatch(
                "effect authorization registry does not contain the exact promotion row"
            )
        return row

    rows = tuple(row for row in registry if row.id == PROMOTION_ENTRYPOINT_ID)
    if len(rows) != 1:
        raise PromotionEffectBindingMismatch(
            "effect authorization registry must contain exactly one promotion row"
        )
    return rows[0]


def _guard_map(decisions: Iterable[GuardDecision]) -> dict[str, GuardDecision]:
    rows: dict[str, GuardDecision] = {}
    for decision in decisions:
        if not isinstance(decision, GuardDecision):
            raise PromotionEffectBindingMismatch(
                "promotion effect guard decisions must use GuardDecision"
            )
        if decision.contract in rows:
            raise PromotionEffectBindingMismatch(
                f"duplicate promotion guard decision: {decision.contract}"
            )
        rows[decision.contract] = decision
    return rows


@dataclass(frozen=True)
class PromotionEffectCapability:
    """One exact, already-issued non-runtime capability for one promotion.

    Construction is effect-free.  ``grant()``, ``begin()`` and ``finish()``
    delegate to the canonical persisted Effect-Lease authority; this adapter
    never issues a lease, invokes Git, opens a worktree, mutates a repository or
    synthesizes OwnerApproval.
    """

    promotion: PromotionAuthorization
    authorization: NonRuntimeEffectAuthorization = field(repr=False)
    execution: EffectExecutionRequest

    def __post_init__(self) -> None:
        promotion_digest = _promotion_authorization_digest(self.promotion)
        if not isinstance(self.authorization, NonRuntimeEffectAuthorization):
            raise PromotionEffectBindingMismatch(
                "promotion effect capability requires NonRuntimeEffectAuthorization"
            )
        if not isinstance(self.execution, EffectExecutionRequest):
            raise PromotionEffectBindingMismatch(
                "promotion effect capability requires EffectExecutionRequest"
            )

        row = _registry_row(self.authorization.registry)
        row_effects = tuple(sorted(effect.value for effect in row.effects))
        row_guards = tuple(sorted(row.guard_contracts))
        row_mismatches = []
        if row.target != PROMOTION_TARGET:
            row_mismatches.append("target")
        if row_effects != PROMOTION_EFFECTS:
            row_mismatches.append("effects")
        if row_guards != PROMOTION_GUARD_CONTRACTS:
            row_mismatches.append("guard_contracts")
        if row.wiring is not Wiring.CENTRAL:
            row_mismatches.append("wiring")
        if row.runtime_id:
            row_mismatches.append("runtime_id")
        if row_mismatches:
            raise PromotionEffectBindingMismatch(
                "promotion registry row mismatch: " + ", ".join(row_mismatches)
            )

        request = self.authorization.request
        lease = self.authorization.lease
        comparisons = {
            "request_entrypoint": (request.entrypoint_id, PROMOTION_ENTRYPOINT_ID),
            "lease_entrypoint": (lease.entrypoint_id, PROMOTION_ENTRYPOINT_ID),
            "request_effects": (request.requested_effects, PROMOTION_EFFECTS),
            "lease_effects": (lease.requested_effects, PROMOTION_EFFECTS),
            "request_attempt": (request.attempt_id, self.promotion.promotion_id),
            "request_revision": (
                request.provenance.source_revision,
                self.promotion.source_revision,
            ),
            "lease_revision": (
                lease.provenance.source_revision,
                self.promotion.source_revision,
            ),
            "execution_id": (
                self.execution.execution_id,
                self.promotion.promotion_id,
            ),
            "idempotency_key": (
                self.execution.idempotency_key,
                promotion_digest,
            ),
            "execution_effects": (
                self.execution.requested_effects,
                PROMOTION_EFFECTS,
            ),
        }
        mismatches = sorted(
            name for name, (actual, expected) in comparisons.items() if actual != expected
        )
        if mismatches:
            raise PromotionEffectBindingMismatch(
                "promotion effect subject mismatch: " + ", ".join(mismatches)
            )

        required_inputs = {
            promotion_digest,
            self.promotion.candidate_artifact_sha256,
            self.promotion.evidence_packet_sha256,
            self.promotion.approval_consumption_sha256,
        }
        missing_inputs = sorted(
            required_inputs - set(request.provenance.input_digests)
        )
        if missing_inputs:
            raise PromotionEffectBindingMismatch(
                "effect lease request provenance does not bind the promotion subject: "
                + ", ".join(missing_inputs)
            )

        scope = request.effect_scope
        hidden_authority = []
        if scope.egress_endpoints or self.execution.egress_endpoints:
            hidden_authority.append("egress")
        if scope.secret_refs or self.execution.secret_refs:
            hidden_authority.append("secrets")
        if scope.max_cost_microusd is not None or self.execution.max_cost_microusd:
            hidden_authority.append("spend")
        if "git" not in scope.tools or "git" not in self.execution.tools:
            hidden_authority.append("git_tool")
        if hidden_authority:
            raise PromotionEffectBindingMismatch(
                "promotion effect scope contains missing or hidden authority: "
                + ", ".join(sorted(hidden_authority))
            )

        guards = _guard_map(self.authorization.guard_decisions)
        if tuple(sorted(guards)) != PROMOTION_GUARD_CONTRACTS:
            raise PromotionEffectBindingMismatch(
                "promotion effect capability does not carry the exact guard set"
            )
        denied = sorted(name for name, decision in guards.items() if not decision.allowed)
        empty = sorted(name for name, decision in guards.items() if not decision.evidence.strip())
        if denied or empty:
            raise PromotionEffectBindingMismatch(
                "promotion effect capability carries denied or empty guard evidence"
            )
        expected_owner_evidence = (
            "artifact:sha256:" + self.promotion.approval_consumption_sha256
        )
        if guards["promotion.owner_approval"].evidence != expected_owner_evidence:
            raise PromotionEffectBindingMismatch(
                "owner-approval guard evidence does not bind approval consumption"
            )

    def grant(self) -> None:
        """Persist the exact already-issued lease; no promotion effect occurs."""

        self.authorization.grant()

    def begin(self) -> EffectStartResult:
        """Commit the exact effect start before any later promotion mutation."""

        return self.authorization.begin_effect(self.execution)

    def finish(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        """Persist one terminal receipt through the canonical lease authority."""

        return self.authorization.finish_effect(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )


__all__ = [
    "PROMOTION_EFFECTS",
    "PROMOTION_ENTRYPOINT_ID",
    "PROMOTION_GUARD_CONTRACTS",
    "PROMOTION_TARGET",
    "PromotionEffectBindingMismatch",
    "PromotionEffectCapability",
]
