"""Runtime-bound reconciliation for provider effects with unknown outcomes.

This adapter authenticates the exact runtime capability at the durable start
instant and binds it to the entrypoint, lease, execution, idempotency key and
source revision before delegating to the generic signed-observation recovery
operation.  It never invokes a provider and accepts only an already STARTED
execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Sequence

from daedalus.kernel.effect_recovery import (
    EffectRecoveryResult,
    ExternalEffectObservation,
    reconcile_unknown_effect,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseError,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    RuntimeLeaseAdmissionError,
    verify_runtime_bound_effect_lease,
)
from daedalus.spine.effect_boundary import EntrypointSpec, Wiring


class RuntimeProviderRecoveryError(RuntimeError):
    """Base class for runtime-bound unknown-outcome recovery failures."""


class RuntimeProviderRecoveryBindingError(RuntimeProviderRecoveryError):
    """The recovery material does not bind one exact runtime provider start."""


def _parse_start(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RuntimeProviderRecoveryBindingError(
            "start receipt timestamp is malformed"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeProviderRecoveryBindingError(
            "start receipt timestamp is timezone-naive"
        )
    return parsed.astimezone(timezone.utc)


def _registry_map(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> dict[str, EntrypointSpec]:
    if isinstance(registry, Mapping):
        rows = dict(registry)
        if any(key != value.id for key, value in rows.items()):
            raise RuntimeProviderRecoveryBindingError(
                "runtime recovery registry contains mismatched key/id rows"
            )
        return rows
    rows = tuple(registry)
    if len({row.id for row in rows}) != len(rows):
        raise RuntimeProviderRecoveryBindingError(
            "runtime recovery registry contains duplicate entrypoint ids"
        )
    return {row.id: row for row in rows}


def _validate_runtime_binding(
    entrypoint_id: str,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    expected_source_revision: str,
) -> None:
    if type(authorization) is not RuntimeBoundEffectAuthorization:
        raise RuntimeProviderRecoveryBindingError(
            "authorization must be an exact RuntimeBoundEffectAuthorization"
        )
    if type(execution) is not EffectExecutionRequest:
        raise RuntimeProviderRecoveryBindingError(
            "execution must be an exact EffectExecutionRequest"
        )
    if type(start_receipt) is not LeasedEffectStartReceipt:
        raise RuntimeProviderRecoveryBindingError(
            "start_receipt must be an exact LeasedEffectStartReceipt"
        )
    if not isinstance(entrypoint_id, str) or not entrypoint_id.strip():
        raise RuntimeProviderRecoveryBindingError("entrypoint_id must be non-empty")
    expected = entrypoint_id.strip()
    spec = _registry_map(authorization.registry).get(expected)
    if spec is None:
        raise RuntimeProviderRecoveryBindingError(
            "runtime recovery entrypoint is absent from the registry"
        )
    comparisons = {
        "request_entrypoint": (authorization.request.entrypoint_id, expected),
        "lease_entrypoint": (
            authorization.capability.lease.entrypoint_id,
            expected,
        ),
        "spec_runtime": (spec.runtime_id, authorization.capability.runtime_id),
        "lease_runtime": (
            authorization.capability.lease.runtime_id,
            authorization.capability.runtime_id,
        ),
        "lease_sha256": (
            start_receipt.lease_sha256,
            authorization.capability.lease.digest,
        ),
        "execution_id": (
            start_receipt.execution_id,
            execution.execution_id,
        ),
        "idempotency_key": (
            start_receipt.idempotency_key,
            execution.idempotency_key,
        ),
        "execution_request_sha256": (
            start_receipt.execution_request_sha256,
            execution.digest,
        ),
        "source_revision": (
            authorization.capability.source_revision,
            expected_source_revision,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, required) in comparisons.items()
        if actual != required
    )
    if spec.wiring is not Wiring.CENTRAL:
        mismatches.append("wiring")
    if not spec.runtime_id:
        mismatches.append("runtime_id")
    if mismatches:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery binding mismatch: "
            + ", ".join(sorted(set(mismatches)))
        )

    try:
        verify_runtime_bound_effect_lease(
            authorization.capability,
            request=authorization.request,
            policy_decision=authorization.policy_decision,
            lease_keyring=authorization.lease_keyring,
            runtime_authority_keyring=authorization.runtime_authority_keyring,
            runtime_trust_ledger=authorization.runtime_trust_ledger,
            current_kill_switch_generation=(
                authorization.current_kill_switch_generation
            ),
            now=_parse_start(start_receipt.started_at),
            registry=authorization.registry,
        )
    except (EffectLeaseError, RuntimeLeaseAdmissionError, ValueError) as exc:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery capability failed authentication"
        ) from exc


def reconcile_runtime_provider_unknown(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    observation: ExternalEffectObservation,
    observation_keyring: Mapping[str, bytes | str],
    expected_provider_id: str,
    expected_source_revision: str,
    reconciled_at: datetime,
) -> EffectRecoveryResult:
    """Reconcile one STARTED provider effect without invoking it again."""

    _validate_runtime_binding(
        entrypoint_id,
        authorization,
        execution,
        start_receipt,
        expected_source_revision,
    )
    return reconcile_unknown_effect(
        authorization.effect_ledger,
        execution=execution,
        start_receipt=start_receipt,
        observation=observation,
        keyring=observation_keyring,
        expected_provider_id=expected_provider_id,
        expected_source_revision=expected_source_revision,
        reconciled_at=reconciled_at,
    )


__all__ = [
    "RuntimeProviderRecoveryBindingError",
    "RuntimeProviderRecoveryError",
    "reconcile_runtime_provider_unknown",
]
