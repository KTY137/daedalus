# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Bridge Ikarus one-shot intent into the canonical Daedalus effect kernel.

This module deliberately does not issue policy decisions, leases, runtime trust,
provider observation authority, or provider calls.  It converts an already
bounded one-shot request and its policy-projected tool scope into the existing
``EffectLeaseRequest`` / ``EffectExecutionRequest`` wire language.  The normal
runtime lease issuer and ``daedalus.runtimes.broker`` remain the only authority
that can admit and execute the external effect.

The bridge exists to remove an architectural gap rather than create another
control plane: Ikarus request identity, runtime evidence, tool-policy evidence,
resource bounds, kill switch and workspace/egress/secret scope become explicit
inputs of the canonical kernel request.  There is no ambient provider config or
runtime-owned widening seam.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .schemas import ContractProvenance, EffectScope
from .spine.effect_boundary import Effect


class IkarusEffectBridgeRefused(RuntimeError):
    """Ikarus intent cannot be represented without broadening canonical scope."""


def _instant(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise IkarusEffectBridgeRefused("created_at must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _effect_ids(values: Iterable[str | Effect]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise IkarusEffectBridgeRefused("requested_effects must be an iterable")
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise IkarusEffectBridgeRefused("requested_effects must be iterable") from exc
    normalized: list[str] = []
    for index, value in enumerate(rows):
        try:
            normalized.append((value if isinstance(value, Effect) else Effect(value)).value)
        except (TypeError, ValueError) as exc:
            raise IkarusEffectBridgeRefused(
                f"requested_effects[{index}] is not a canonical Effect"
            ) from exc
    if not normalized:
        raise IkarusEffectBridgeRefused("requested_effects must not be empty")
    if len(set(normalized)) != len(normalized):
        raise IkarusEffectBridgeRefused("requested_effects must not contain duplicates")
    return tuple(sorted(normalized))


def _bind_subjects(
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    tool_scope: IkarusToolScopeProjection,
) -> None:
    if type(request) is not OneShotRequest:
        raise IkarusEffectBridgeRefused("request must be an exact OneShotRequest")
    if type(runtime_evidence) is not OneShotRuntimeEvidenceBinding:
        raise IkarusEffectBridgeRefused(
            "runtime_evidence must be an exact OneShotRuntimeEvidenceBinding"
        )
    if type(tool_scope) is not IkarusToolScopeProjection:
        raise IkarusEffectBridgeRefused(
            "tool_scope must be an exact IkarusToolScopeProjection"
        )
    mismatches: list[str] = []
    if runtime_evidence.request_sha256 != request.digest:
        mismatches.append("runtime evidence request")
    if runtime_evidence.runtime_id != request.runtime_id:
        mismatches.append("runtime identity")
    if tool_scope.request_sha256 != request.digest:
        mismatches.append("tool scope request")
    if tool_scope.runtime_evidence_sha256 != runtime_evidence.digest:
        mismatches.append("tool scope runtime evidence")
    if tool_scope.runtime_manifest_sha256 != runtime_evidence.runtime_manifest_sha256:
        mismatches.append("tool scope runtime manifest")
    if mismatches:
        raise IkarusEffectBridgeRefused(
            "Ikarus effect bridge subject mismatch: " + ", ".join(sorted(mismatches))
        )


def _require_scope_effects(scope: EffectScope, effects: tuple[str, ...]) -> None:
    effect_set = set(effects)
    required: list[str] = []
    if scope.writable_paths and Effect.FILESYSTEM_WRITE.value not in effect_set:
        required.append(Effect.FILESYSTEM_WRITE.value)
    if scope.egress_endpoints and Effect.NETWORK_EGRESS.value not in effect_set:
        required.append(Effect.NETWORK_EGRESS.value)
    if scope.secret_refs and Effect.SECRETS.value not in effect_set:
        required.append(Effect.SECRETS.value)
    if Effect.SPEND.value in effect_set and scope.max_cost_microusd is None:
        raise IkarusEffectBridgeRefused(
            "a spend effect requires an explicit one-shot cost bound"
        )
    if required:
        raise IkarusEffectBridgeRefused(
            "effect scope requires missing canonical effect(s): "
            + ", ".join(sorted(required))
        )


def build_oneshot_effect_lease_request(
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    tool_scope: IkarusToolScopeProjection,
    *,
    request_id: str,
    mission_id: str,
    attempt_id: str,
    entrypoint_id: str,
    idempotency_namespace: str,
    kill_switch_ref: str,
    kill_switch_generation: int,
    requested_effects: Iterable[str | Effect],
    created_at: datetime,
    writable_paths: Iterable[str] = (),
    egress_endpoints: Iterable[str] = (),
    secret_refs: Iterable[str] = (),
    timeout_s: int | None = None,
) -> EffectLeaseRequest:
    """Project one bounded Ikarus call into the canonical lease-request type.

    ``requested_effects`` remains explicit because a remote HTTP provider, a
    local subprocess runtime and a future contained runtime do not have the same
    effect set.  Scope-bearing facts are nevertheless cross-checked: write,
    egress and secret scopes cannot be requested without their corresponding
    canonical effects, and spend cannot be requested without a cost ceiling.
    """

    _bind_subjects(request, runtime_evidence, tool_scope)
    effects = _effect_ids(requested_effects)
    try:
        writes = tuple(writable_paths)
        egress = tuple(egress_endpoints)
        secrets = tuple(secret_refs)
    except TypeError as exc:
        raise IkarusEffectBridgeRefused(
            "workspace, egress and secret scopes must be iterable"
        ) from exc

    wall_limit = request.budget.max_wall_time_s
    assert wall_limit is not None  # OneShotRequest validates this structurally.
    effective_timeout = wall_limit if timeout_s is None else timeout_s
    if (
        isinstance(effective_timeout, bool)
        or not isinstance(effective_timeout, int)
        or effective_timeout < 1
        or effective_timeout > wall_limit
    ):
        raise IkarusEffectBridgeRefused(
            "effect timeout must be positive and no broader than the one-shot wall-time budget"
        )

    try:
        scope = EffectScope(
            read_only=not bool(writes),
            writable_paths=writes,
            egress_endpoints=egress,
            tools=tool_scope.enabled_tools,
            secret_refs=secrets,
            max_cost_microusd=request.budget.max_cost_microusd,
            max_concurrency=1,
            timeout_s=effective_timeout,
            kill_switch_ref=kill_switch_ref,
        )
    except (TypeError, ValueError) as exc:
        raise IkarusEffectBridgeRefused("canonical effect scope is malformed") from exc
    _require_scope_effects(scope, effects)

    provenance_inputs = tuple(
        sorted(
            {
                request.digest,
                runtime_evidence.digest,
                runtime_evidence.runtime_manifest_sha256,
                runtime_evidence.runtime_conformance_sha256,
                tool_scope.digest,
                tool_scope.policy_decision_sha256,
            }
        )
    )
    try:
        provenance = ContractProvenance(
            origin="ikarus.oneshot-effect-kernel-bridge",
            source_revision=runtime_evidence.source_revision,
            created_at=_instant(created_at),
            input_digests=provenance_inputs,
            trace_id=mission_id,
        )
        return EffectLeaseRequest(
            request_id=request_id,
            mission_id=mission_id,
            attempt_id=attempt_id,
            entrypoint_id=entrypoint_id,
            requested_effects=effects,
            effect_scope=scope,
            idempotency_namespace=idempotency_namespace,
            kill_switch_generation=kill_switch_generation,
            runtime_manifest_sha256=runtime_evidence.runtime_manifest_sha256,
            runtime_conformance_sha256=runtime_evidence.runtime_conformance_sha256,
            provenance=provenance,
        )
    except (TypeError, ValueError) as exc:
        raise IkarusEffectBridgeRefused(
            "canonical EffectLeaseRequest refused the projected Ikarus subject"
        ) from exc


def build_oneshot_effect_execution_request(
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    tool_scope: IkarusToolScopeProjection,
    effect_request: EffectLeaseRequest,
    *,
    execution_id: str,
    idempotency_key: str,
    requested_effects: Iterable[str | Effect] | None = None,
    writable_paths: Iterable[str] | None = None,
    egress_endpoints: Iterable[str] | None = None,
    secret_refs: Iterable[str] | None = None,
    max_cost_microusd: int | None = None,
) -> EffectExecutionRequest:
    """Create the exact narrowed execution request consumed by the broker.

    The execution may narrow effects, paths, endpoints, secrets and cost, but it
    cannot add any scope that was not present in the lease request.  Ikarus tool
    exposure is exact: the provider execution receives precisely the final
    policy-projected enabled tool set, never ambient or caller-added tools.
    """

    _bind_subjects(request, runtime_evidence, tool_scope)
    if type(effect_request) is not EffectLeaseRequest:
        raise IkarusEffectBridgeRefused(
            "effect_request must be an exact EffectLeaseRequest"
        )
    required_inputs = {
        request.digest,
        runtime_evidence.digest,
        tool_scope.digest,
        tool_scope.policy_decision_sha256,
    }
    if not required_inputs.issubset(set(effect_request.provenance.input_digests)):
        raise IkarusEffectBridgeRefused(
            "effect request provenance is not bound to this Ikarus request and tool scope"
        )
    comparisons = {
        "source revision": (
            effect_request.provenance.source_revision,
            runtime_evidence.source_revision,
        ),
        "runtime manifest": (
            effect_request.runtime_manifest_sha256,
            runtime_evidence.runtime_manifest_sha256,
        ),
        "runtime conformance": (
            effect_request.runtime_conformance_sha256,
            runtime_evidence.runtime_conformance_sha256,
        ),
        "tool scope": (effect_request.effect_scope.tools, tool_scope.enabled_tools),
    }
    mismatch = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatch:
        raise IkarusEffectBridgeRefused(
            "effect request differs from the Ikarus projection: " + ", ".join(mismatch)
        )

    effects = (
        effect_request.requested_effects
        if requested_effects is None
        else _effect_ids(requested_effects)
    )
    if not set(effects).issubset(set(effect_request.requested_effects)):
        raise IkarusEffectBridgeRefused(
            "execution requested_effects cannot broaden the lease request"
        )

    def narrowed(values, granted, label: str) -> tuple[str, ...]:
        rows = tuple(granted) if values is None else tuple(values)
        if not set(rows).issubset(set(granted)):
            raise IkarusEffectBridgeRefused(
                f"execution {label} cannot broaden the lease request"
            )
        return rows

    writes = narrowed(writable_paths, effect_request.effect_scope.writable_paths, "writable_paths")
    egress = narrowed(egress_endpoints, effect_request.effect_scope.egress_endpoints, "egress_endpoints")
    secrets = narrowed(secret_refs, effect_request.effect_scope.secret_refs, "secret_refs")

    granted_cost = effect_request.effect_scope.max_cost_microusd
    if max_cost_microusd is None:
        execution_cost = 0 if granted_cost is None else granted_cost
    else:
        if isinstance(max_cost_microusd, bool) or not isinstance(max_cost_microusd, int) or max_cost_microusd < 0:
            raise IkarusEffectBridgeRefused(
                "execution max_cost_microusd must be a non-negative integer"
            )
        execution_cost = max_cost_microusd
    if granted_cost is not None and execution_cost > granted_cost:
        raise IkarusEffectBridgeRefused(
            "execution cost cannot exceed the one-shot lease-request bound"
        )

    execution_scope = EffectScope(
        read_only=not bool(writes),
        writable_paths=writes,
        egress_endpoints=egress,
        tools=tool_scope.enabled_tools,
        secret_refs=secrets,
        max_cost_microusd=execution_cost,
        max_concurrency=1,
        timeout_s=effect_request.effect_scope.timeout_s,
        kill_switch_ref=effect_request.effect_scope.kill_switch_ref,
    )
    _require_scope_effects(execution_scope, effects)
    try:
        return EffectExecutionRequest(
            execution_id=execution_id,
            idempotency_key=idempotency_key,
            requested_effects=effects,
            writable_paths=writes,
            egress_endpoints=egress,
            tools=tool_scope.enabled_tools,
            secret_refs=secrets,
            max_cost_microusd=execution_cost,
            kill_switch_ref=effect_request.effect_scope.kill_switch_ref,
            kill_switch_generation=effect_request.kill_switch_generation,
        )
    except (TypeError, ValueError) as exc:
        raise IkarusEffectBridgeRefused(
            "canonical EffectExecutionRequest refused the narrowed Ikarus execution"
        ) from exc


__all__ = [
    "IkarusEffectBridgeRefused",
    "build_oneshot_effect_execution_request",
    "build_oneshot_effect_lease_request",
]
