# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Runtime-bound reconciliation for provider effects with unknown outcomes.

This adapter authenticates the exact persisted runtime execution at its durable
start instant, loads the pre-invocation provider-observation binding, and derives
both provider identity and accepted observation keys from retained authenticated
material.  Recovery callers cannot supply or replace either trust dimension.

The adapter never invokes a provider and accepts only an already STARTED
execution that is pending reconciliation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from daedalus.kernel.effect_recovery import (
    EffectRecoveryResult,
    ExternalEffectObservation,
    reconcile_unknown_effect,
)
from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.kernel.runtime_effect_replay import (
    RuntimeEffectExecutionReplaySnapshot,
    RuntimeEffectReplayProjectionError,
    inspect_runtime_effect_execution,
)
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthorityError,
    ProviderObservationBindingLedger,
)
from daedalus.spine.effect_boundary import EntrypointSpec, Wiring


class RuntimeProviderRecoveryError(RuntimeError):
    """Base class for runtime-bound unknown-outcome recovery failures."""


class RuntimeProviderRecoveryBindingError(RuntimeProviderRecoveryError):
    """The recovery material does not bind one exact runtime provider start."""


def _registry_map(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> dict[str, EntrypointSpec]:
    try:
        if isinstance(registry, Mapping):
            rows = dict(registry)
            if any(
                type(value) is not EntrypointSpec or key != value.id
                for key, value in rows.items()
            ):
                raise RuntimeProviderRecoveryBindingError(
                    "runtime recovery registry contains malformed key/id rows"
                )
            return rows
        if isinstance(registry, (str, bytes)):
            raise TypeError("registry sequence cannot be text")
        rows = tuple(registry)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeProviderRecoveryBindingError(
            "runtime recovery registry is malformed"
        ) from exc
    if any(type(row) is not EntrypointSpec for row in rows):
        raise RuntimeProviderRecoveryBindingError(
            "runtime recovery registry contains malformed rows"
        )
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
) -> RuntimeEffectExecutionReplaySnapshot:
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
    try:
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
        }
    except AttributeError as exc:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery subject is malformed"
        ) from exc
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
        replay = inspect_runtime_effect_execution(authorization, execution)
    except RuntimeEffectReplayProjectionError as exc:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery execution failed authenticated replay"
        ) from exc
    if replay is None:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery execution has no durable start"
        )
    if type(replay) is not RuntimeEffectExecutionReplaySnapshot:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery replay type is invalid"
        )
    if replay.execution.start_receipt != start_receipt:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery start receipt differs from persisted replay"
        )
    if not replay.pending_reconciliation:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery execution is already terminal"
        )
    return replay


def _load_provider_binding(
    *,
    entrypoint_id: str,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    observation: ExternalEffectObservation,
    ledger: ProviderObservationBindingLedger,
):
    if type(ledger) is not ProviderObservationBindingLedger:
        raise RuntimeProviderRecoveryBindingError(
            "observation_binding_ledger must be an exact "
            "ProviderObservationBindingLedger"
        )
    try:
        record = ledger.load(execution.execution_id)
        if record is None:
            raise RuntimeProviderRecoveryBindingError(
                "runtime provider recovery has no retained observation authority"
            )
        ledger.require_bound(
            record.authority,
            start_receipt,
            entrypoint_id=entrypoint_id,
            runtime_id=authorization.capability.runtime_id,
            execution=execution,
            lease_sha256=authorization.capability.lease.digest,
            source_revision=authorization.capability.source_revision,
        )
    except RuntimeProviderRecoveryBindingError:
        raise
    except (AttributeError, ProviderObservationAuthorityError, ValueError) as exc:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery observation authority failed authentication"
        ) from exc
    if type(observation) is not ExternalEffectObservation:
        raise RuntimeProviderRecoveryBindingError(
            "observation must be an exact ExternalEffectObservation"
        )
    if observation.provider_id != record.authority.provider_id:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery observation provider differs from retained authority"
        )
    if observation.issuer_key_id not in record.authority.observation_issuer_key_ids:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery observation issuer is not retained"
        )
    return record


def reconcile_runtime_provider_unknown(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    observation: ExternalEffectObservation,
    observation_binding_ledger: ProviderObservationBindingLedger,
    reconciled_at: datetime,
) -> EffectRecoveryResult:
    """Reconcile one STARTED provider effect without invoking it again."""

    _validate_runtime_binding(
        entrypoint_id,
        authorization,
        execution,
        start_receipt,
    )
    record = _load_provider_binding(
        entrypoint_id=entrypoint_id.strip(),
        authorization=authorization,
        execution=execution,
        start_receipt=start_receipt,
        observation=observation,
        ledger=observation_binding_ledger,
    )
    try:
        return reconcile_unknown_effect(
            authorization.effect_ledger,
            execution=execution,
            start_receipt=start_receipt,
            observation=observation,
            keyring=observation_binding_ledger.observation_keyring,
            expected_provider_id=record.authority.provider_id,
            expected_source_revision=record.authority.source_revision,
            reconciled_at=reconciled_at,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeProviderRecoveryBindingError(
            "runtime provider recovery delegated subject is malformed"
        ) from exc


__all__ = [
    "RuntimeProviderRecoveryBindingError",
    "RuntimeProviderRecoveryError",
    "reconcile_runtime_provider_unknown",
]
