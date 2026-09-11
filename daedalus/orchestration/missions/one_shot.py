"""Fail-closed composition seam for already-built Ikarus one-shot subjects.

This module grants no authority and performs no effect.  It verifies that the
five existing subjects describe one exact mission work item and then checks
whether their registered entrypoint has a centrally admitted one-shot
consumer.  Gate 1 has no such consumer, so every otherwise-valid bundle is
refused before :class:`WaveExecutor` can run.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from daedalus.build import BuildSession
from daedalus.orchestration.ikarus.effect_bridge import (
    IkarusEffectBridgeRefused,
    build_oneshot_effect_execution_request,
    build_oneshot_effect_lease_request,
)
from daedalus.orchestration.ikarus.oneshot import (
    OneShotRequest,
    OneShotRuntimeEvidenceBinding,
    OneShotRuntimeRefused,
)
from daedalus.orchestration.ikarus.tool_scope import IkarusToolScopeProjection
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.schemas import MissionContract
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Wiring


OneShotEffectSubjects = tuple[
    OneShotRequest,
    OneShotRuntimeEvidenceBinding,
    IkarusToolScopeProjection,
    EffectLeaseRequest,
    EffectExecutionRequest,
]


def _bounded_by(value: int | None, ceiling: int | None, label: str) -> None:
    if ceiling is not None and (value is None or value > ceiling):
        raise IkarusEffectBridgeRefused(
            f"{label} is broader than the canonical mission budget"
        )


def _created_at(effect_request: EffectLeaseRequest) -> datetime:
    value = effect_request.provenance.created_at
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise IkarusEffectBridgeRefused(
            "one-shot effect provenance created_at is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IkarusEffectBridgeRefused(
            "one-shot effect provenance created_at must include a timezone"
        )
    return parsed


def _exact_bundle(value: object) -> OneShotEffectSubjects:
    if type(value) is not tuple or len(value) != 5:
        raise IkarusEffectBridgeRefused(
            "one-shot work item requires exactly five immutable subjects"
        )
    request, evidence, tools, effect_request, execution = value
    expected = (
        (request, OneShotRequest, "request"),
        (evidence, OneShotRuntimeEvidenceBinding, "runtime evidence"),
        (tools, IkarusToolScopeProjection, "tool scope"),
        (effect_request, EffectLeaseRequest, "effect request"),
        (execution, EffectExecutionRequest, "execution request"),
    )
    for subject, subject_type, label in expected:
        if type(subject) is not subject_type:
            raise IkarusEffectBridgeRefused(
                f"one-shot {label} must be an exact {subject_type.__name__}"
            )
    return value


def _verify_bundle(
    mission: MissionContract,
    work_item_id: str,
    bundle: OneShotEffectSubjects,
) -> None:
    request, evidence, tools, effect_request, execution = bundle
    comparisons = {
        "mission": (effect_request.mission_id, mission.mission_id),
        "attempt/work item": (effect_request.attempt_id, work_item_id),
        "trace": (effect_request.provenance.trace_id, mission.mission_id),
        "runtime evidence request": (evidence.request_sha256, request.digest),
        "runtime identity": (evidence.runtime_id, request.runtime_id),
        "runtime role": (evidence.role, request.role),
        "runtime binding": (
            evidence.runtime_binding_sha256,
            request.runtime_binding_sha256,
        ),
        "tool request": (tools.request_sha256, request.digest),
        "tool runtime evidence": (
            tools.runtime_evidence_sha256,
            evidence.digest,
        ),
        "tool runtime manifest": (
            tools.runtime_manifest_sha256,
            evidence.runtime_manifest_sha256,
        ),
    }
    mismatch = sorted(
        name for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatch:
        raise IkarusEffectBridgeRefused(
            "one-shot subjects do not name one mission work item: "
            + ", ".join(mismatch)
        )

    _bounded_by(
        request.budget.max_cost_microusd,
        mission.budget.max_cost_microusd,
        "one-shot cost bound",
    )
    _bounded_by(
        request.budget.max_wall_time_s,
        mission.budget.max_wall_time_s,
        "one-shot wall-time bound",
    )
    _bounded_by(
        effect_request.effect_scope.max_cost_microusd,
        mission.budget.max_cost_microusd,
        "effect-request cost bound",
    )
    _bounded_by(
        effect_request.effect_scope.timeout_s,
        mission.budget.max_wall_time_s,
        "effect-request timeout",
    )
    _bounded_by(
        execution.max_cost_microusd,
        mission.budget.max_cost_microusd,
        "execution cost bound",
    )
    if (
        effect_request.operation_sha256 is not None
        or execution.operation_sha256 is not None
    ):
        raise IkarusEffectBridgeRefused(
            "Ikarus one-shot subjects cannot carry an unverified operation plan"
        )

    rebuilt_request = build_oneshot_effect_lease_request(
        request,
        evidence,
        tools,
        request_id=effect_request.request_id,
        mission_id=effect_request.mission_id,
        attempt_id=effect_request.attempt_id,
        entrypoint_id=effect_request.entrypoint_id,
        idempotency_namespace=effect_request.idempotency_namespace,
        kill_switch_ref=effect_request.effect_scope.kill_switch_ref,
        kill_switch_generation=effect_request.kill_switch_generation,
        requested_effects=effect_request.requested_effects,
        created_at=_created_at(effect_request),
        writable_paths=effect_request.effect_scope.writable_paths,
        egress_endpoints=effect_request.effect_scope.egress_endpoints,
        secret_refs=effect_request.effect_scope.secret_refs,
        timeout_s=effect_request.effect_scope.timeout_s,
    )
    if (
        rebuilt_request != effect_request
        or rebuilt_request.digest != effect_request.digest
    ):
        raise IkarusEffectBridgeRefused(
            "effect request is not the exact canonical one-shot projection"
        )

    rebuilt_execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        requested_effects=execution.requested_effects,
        writable_paths=execution.writable_paths,
        egress_endpoints=execution.egress_endpoints,
        secret_refs=execution.secret_refs,
        max_cost_microusd=execution.max_cost_microusd,
    )
    if (
        rebuilt_execution != execution
        or rebuilt_execution.digest != execution.digest
    ):
        raise IkarusEffectBridgeRefused(
            "execution request is not the exact narrowed one-shot projection"
        )


def validate_one_shot_effects(
    session: BuildSession,
    mission: MissionContract,
    subjects: Mapping[str, object],
) -> None:
    """Validate exact one-shot subjects, then require admitted composition.

    The current Gate-1 registry deliberately contains no centrally admitted
    Hermes/one-shot runtime entrypoint and ``WaveExecutor`` has no consumer for
    these subjects.  Consequently this function can only return after a future
    packet provides both facts; today it always raises before execution.
    """

    if type(session) is not BuildSession or type(mission) is not MissionContract:
        raise IkarusEffectBridgeRefused(
            "one-shot validation requires exact mission/session contracts"
        )
    if not isinstance(subjects, Mapping):
        raise IkarusEffectBridgeRefused(
            "one-shot subjects must be mapped by work_item_id"
        )
    expected_ids = tuple(session.work_item_ids())
    if set(subjects) != set(expected_ids):
        raise IkarusEffectBridgeRefused(
            "one-shot subject keys must exactly equal the mission work items"
        )

    bundles: list[OneShotEffectSubjects] = []
    request_digests: set[str] = set()
    request_ids: set[str] = set()
    attempt_ids: set[str] = set()
    execution_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    for work_item_id in expected_ids:
        bundle = _exact_bundle(subjects[work_item_id])
        _verify_bundle(mission, work_item_id, bundle)
        request, _evidence, _tools, effect_request, execution = bundle
        identities = (
            (request_digests, request.digest, "one-shot request digest"),
            (request_ids, effect_request.request_id, "effect request_id"),
            (attempt_ids, effect_request.attempt_id, "attempt_id"),
            (execution_ids, execution.execution_id, "execution_id"),
            (idempotency_keys, execution.idempotency_key, "idempotency_key"),
        )
        for seen, value, label in identities:
            if value in seen:
                raise IkarusEffectBridgeRefused(
                    f"one-shot {label} is duplicated across work items"
                )
            seen.add(value)
        bundles.append(bundle)

    for request, _evidence, _tools, effect_request, _execution in bundles:
        spec = REGISTRY_BY_ID.get(effect_request.entrypoint_id)
        if spec is None:
            raise OneShotRuntimeRefused(
                f"one-shot entrypoint {effect_request.entrypoint_id!r} is not registered"
            )
        if spec.wiring is not Wiring.CENTRAL:
            raise OneShotRuntimeRefused(
                f"one-shot entrypoint {spec.id!r} is {spec.wiring.value}, not central"
            )
        if spec.runtime_id != request.runtime_id:
            raise OneShotRuntimeRefused(
                "one-shot runtime identity does not match the central entrypoint"
            )

    raise OneShotRuntimeRefused(
        "no centrally admitted WaveExecutor one-shot consumer is installed"
    )


__all__ = ["OneShotEffectSubjects", "validate_one_shot_effects"]
