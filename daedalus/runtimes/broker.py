"""Execute one runtime provider call behind persisted runtime and effect authority.

The broker composes one exact ``RuntimeBoundEffectAuthorization`` with one
``EffectExecutionRequest`` and a zero-argument provider callback. Lease grant
and effect start are durable before external code runs. Exact replay is inert,
and success, failure, cancellation, and runtime-trust loss receive terminal
receipts.

For exact production runtime authority, a signed provider-observation authority
is authenticated before the effect start.  After the durable start, its provider
and observation-key subject is persisted before external code runs.  Exact
replay requires the same retained binding.  Narrow test doubles remain available
through the compatibility seam while callers migrate; they cannot participate
in runtime-bound unknown-outcome recovery.

Once a provider returns, failure to create canonical output evidence is an
unknown external outcome. The execution remains durably ``STARTED`` and must be
reconciled from independently authenticated provider evidence. The broker never
invents a ``FAILED`` receipt merely because local evidence materialization
failed after the external call.

Successful completion is serialized against runtime quarantine, expiry-state
persistence, and evidence rotation. The exact authenticated runtime-trust row is
held under the trust ledger's SQLite writer transaction while the separate
effect ledger persists ``COMPLETED``. The trust transaction is read-only and is
explicitly rolled back after the effect receipt is durable; no cross-database
atomicity is claimed.

This module does not make an existing provider safe merely by existing. A
production provider row may move to ``CENTRAL`` only after its public call path
requires this broker, emits content-addressed output evidence, and has no direct
effectful bypass.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Generic, Iterable, Mapping, Sequence, TypeVar

from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthority,
    ProviderObservationAuthorityError,
    ProviderObservationBindingLedger,
)
from daedalus.spine.effect_boundary import EntrypointSpec, Wiring
from daedalus.spine.envelope import canonical_sha


T = TypeVar("T")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANCEL_EXCEPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)


class RuntimeProviderBrokerError(RuntimeError):
    """Base class for provider-broker boundary failures."""


class RuntimeProviderBindingMismatch(RuntimeProviderBrokerError):
    """The supplied authority does not name the requested provider entrypoint."""


class RuntimeProviderStateError(RuntimeProviderBrokerError):
    """The external call ran but its terminal state could not be persisted."""


class RuntimeProviderTrustFenceError(RuntimeProviderBrokerError):
    """Runtime trust changed or could not be fenced before terminal completion."""


class RuntimeProviderReconciliationRequired(RuntimeProviderBrokerError):
    """A returned provider effect lacks terminal evidence and stays STARTED."""

    def __init__(
        self,
        *,
        entrypoint_id: str,
        runtime_id: str,
        start_receipt: LeasedEffectStartReceipt,
        phase: str,
        cause_sha256: str,
    ) -> None:
        if not isinstance(entrypoint_id, str) or not entrypoint_id:
            raise ValueError("entrypoint_id must be non-empty")
        if not isinstance(runtime_id, str) or not runtime_id:
            raise ValueError("runtime_id must be non-empty")
        if not isinstance(start_receipt, LeasedEffectStartReceipt):
            raise ValueError("start_receipt must be LeasedEffectStartReceipt")
        if phase != "output-evidence":
            raise ValueError("reconciliation phase is unsupported")
        if not isinstance(cause_sha256, str) or _SHA256_RE.fullmatch(cause_sha256) is None:
            raise ValueError("cause_sha256 must be lowercase SHA-256")
        super().__init__(
            "runtime provider returned but terminal output evidence is unavailable; "
            "authenticated reconciliation is required"
        )
        self.entrypoint_id = entrypoint_id
        self.runtime_id = runtime_id
        self.start_receipt = start_receipt
        self.phase = phase
        self.cause_sha256 = cause_sha256


@dataclass(frozen=True)
class RuntimeInvocationResult(Generic[T]):
    """One durable provider invocation result or an inert exact replay."""

    entrypoint_id: str
    runtime_id: str
    executed: bool
    start_receipt: LeasedEffectStartReceipt
    terminal_receipt: EffectTerminalReceipt | None
    value: T | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _registry_map(
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec],
) -> Mapping[str, EntrypointSpec]:
    try:
        if isinstance(registry, Mapping):
            rows = dict(registry)
            if any(
                type(row) is not EntrypointSpec or key != row.id
                for key, row in rows.items()
            ):
                raise RuntimeProviderBindingMismatch(
                    "runtime authorization registry contains malformed key/id rows"
                )
            return rows
        if isinstance(registry, (str, bytes)):
            raise TypeError("registry sequence cannot be text")
        rows = tuple(registry)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeProviderBindingMismatch(
            "runtime authorization registry is malformed"
        ) from exc
    if any(type(row) is not EntrypointSpec for row in rows):
        raise RuntimeProviderBindingMismatch(
            "runtime authorization registry contains malformed rows"
        )
    if len({row.id for row in rows}) != len(rows):
        raise RuntimeProviderBindingMismatch(
            "runtime authorization registry contains duplicate entrypoint ids"
        )
    return {row.id: row for row in rows}


def _validate_distinct_ledger_paths(
    authorization: RuntimeBoundEffectAuthorization,
) -> None:
    """Refuse a self-deadlocking trust/effect SQLite configuration up front."""

    trust_ledger = getattr(authorization, "runtime_trust_ledger", None)
    effect_ledger = getattr(authorization, "effect_ledger", None)
    trust_path = getattr(trust_ledger, "path", None)
    effect_path = getattr(effect_ledger, "path", None)
    if trust_path is None or effect_path is None:
        return
    try:
        same_path = Path(trust_path).resolve() == Path(effect_path).resolve()
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeProviderBindingMismatch(
            "runtime trust and effect ledger paths cannot be resolved"
        ) from exc
    if same_path:
        raise RuntimeProviderBindingMismatch(
            "runtime trust and effect ledgers must use distinct SQLite files"
        )


def _validate_binding(
    entrypoint_id: str,
    authorization: RuntimeBoundEffectAuthorization,
) -> EntrypointSpec:
    if not isinstance(entrypoint_id, str) or not entrypoint_id.strip():
        raise RuntimeProviderBindingMismatch("entrypoint_id must be non-empty")
    expected = entrypoint_id.strip()
    try:
        comparisons = {
            "request entrypoint": authorization.request.entrypoint_id,
            "lease entrypoint": authorization.capability.lease.entrypoint_id,
        }
    except AttributeError as exc:
        raise RuntimeProviderBindingMismatch(
            "runtime authorization subject is malformed"
        ) from exc
    mismatches = sorted(
        label for label, actual in comparisons.items() if actual != expected
    )
    if mismatches:
        raise RuntimeProviderBindingMismatch(
            "runtime provider authority targets a different entrypoint: "
            + ", ".join(mismatches)
        )

    spec = _registry_map(authorization.registry).get(expected)
    if spec is None:
        raise RuntimeProviderBindingMismatch(
            "runtime provider entrypoint is absent from the authorization registry"
        )
    if spec.wiring is not Wiring.CENTRAL:
        raise RuntimeProviderBindingMismatch(
            "runtime provider entrypoint is not centrally wired"
        )
    if not spec.runtime_id:
        raise RuntimeProviderBindingMismatch(
            "runtime provider entrypoint has no runtime identity"
        )
    if spec.runtime_id != authorization.capability.runtime_id:
        raise RuntimeProviderBindingMismatch(
            "runtime provider identity does not match the bound capability"
        )
    _validate_distinct_ledger_paths(authorization)
    return spec


def _exception_detail(phase: str, exc: BaseException) -> str:
    """Return a deterministic exception-class digest without retaining text."""

    return canonical_sha(
        {
            "phase": phase,
            "exception_module": type(exc).__module__,
            "exception_type": type(exc).__qualname__,
        }
    )


def _normalize_output_digests(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("output digests must be an iterable of SHA-256 strings")
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"output digest {index} must be lowercase SHA-256")
        normalized.append(value)
    if not normalized:
        raise ValueError("a completed runtime provider call requires output evidence")
    if len(set(normalized)) != len(normalized):
        raise ValueError("output digests must not contain duplicates")
    return tuple(sorted(normalized))


def _finish_or_raise_state(
    authorization: RuntimeBoundEffectAuthorization,
    start_receipt: LeasedEffectStartReceipt,
    *,
    outcome: str,
    output_digests: Iterable[str] = (),
    detail_sha256: str | None = None,
) -> EffectTerminalReceipt:
    try:
        return authorization.finish_effect(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )
    except BaseException as exc:
        raise RuntimeProviderStateError(
            "runtime provider terminal receipt could not be persisted"
        ) from exc


def _cancel_for_trust_loss(
    authorization: RuntimeBoundEffectAuthorization,
    start_receipt: LeasedEffectStartReceipt,
    *,
    phase: str,
    error: BaseException,
) -> None:
    _finish_or_raise_state(
        authorization,
        start_receipt,
        outcome="cancelled",
        detail_sha256=_exception_detail(phase, error),
    )


def _parse_record_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RuntimeProviderTrustFenceError(
            "runtime trust record has a malformed expiry"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeProviderTrustFenceError(
            "runtime trust record expiry is timezone-naive"
        )
    return parsed.astimezone(timezone.utc)


def _runtime_fence_components(
    authorization: RuntimeBoundEffectAuthorization,
):
    """Return the concrete persisted trust seam, or ``None`` for narrow doubles."""

    ledger = getattr(authorization, "runtime_trust_ledger", None)
    capability = getattr(authorization, "capability", None)
    if ledger is None:
        return None

    connect = getattr(ledger, "_connect", None)
    from_row = getattr(ledger, "_from_row", None)
    required = (
        "runtime_id",
        "runtime_envelope_sha256",
        "runtime_trust_record_sha256",
        "runtime_manifest_sha256",
        "runtime_conformance_sha256",
        "source_revision",
    )
    if (
        capability is None
        or not callable(connect)
        or not callable(from_row)
        or any(not hasattr(capability, name) for name in required)
    ):
        raise RuntimeProviderBindingMismatch(
            "runtime authorization lacks the persisted terminal-fence seam"
        )
    return ledger, capability


def _rollback_runtime_fence(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        return
    try:
        connection.execute("ROLLBACK")
    except BaseException:
        pass


def _finish_completed_under_runtime_fence(
    authorization: RuntimeBoundEffectAuthorization,
    start_receipt: LeasedEffectStartReceipt,
    *,
    output_digests: tuple[str, ...],
) -> EffectTerminalReceipt:
    """Persist ``COMPLETED`` while quarantine and rotation are serialized out."""

    components = _runtime_fence_components(authorization)
    if components is None:
        return _finish_or_raise_state(
            authorization,
            start_receipt,
            outcome="completed",
            output_digests=output_digests,
        )

    ledger, capability = components
    try:
        connection = ledger._connect()
    except sqlite3.Error as exc:
        raise RuntimeProviderTrustFenceError(
            "runtime trust terminal fence could not open its SQLite authority"
        ) from exc

    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM runtime_trust_records "
            "WHERE runtime_id=? AND envelope_sha256=?",
            (capability.runtime_id, capability.runtime_envelope_sha256),
        ).fetchone()
        if row is None:
            raise RuntimeProviderTrustFenceError(
                "runtime trust record disappeared before terminal completion"
            )
        try:
            record = ledger._from_row(row)
        except BaseException as exc:
            raise RuntimeProviderTrustFenceError(
                "runtime trust record failed authentication at terminal completion"
            ) from exc

        if record.state != "ACTIVE":
            raise RuntimeProviderTrustFenceError(
                "runtime trust was quarantined before terminal completion"
            )
        if _utc_now() >= _parse_record_expiry(record.expires_at):
            raise RuntimeProviderTrustFenceError(
                "runtime trust expired before terminal completion"
            )

        comparisons = {
            "runtime_id": (record.runtime_id, capability.runtime_id),
            "envelope_sha256": (
                record.envelope_sha256,
                capability.runtime_envelope_sha256,
            ),
            "record_sha256": (
                record.record_sha256,
                capability.runtime_trust_record_sha256,
            ),
            "runtime_manifest_sha256": (
                record.runtime_manifest_sha256,
                capability.runtime_manifest_sha256,
            ),
            "conformance_receipt_sha256": (
                record.conformance_receipt_sha256,
                capability.runtime_conformance_sha256,
            ),
            "source_revision": (
                record.source_revision,
                capability.source_revision,
            ),
        }
        mismatches = sorted(
            name
            for name, (actual, expected) in comparisons.items()
            if actual != expected
        )
        if mismatches:
            raise RuntimeProviderTrustFenceError(
                "runtime trust changed before terminal completion: "
                + ", ".join(mismatches)
            )

        terminal = _finish_or_raise_state(
            authorization,
            start_receipt,
            outcome="completed",
            output_digests=output_digests,
        )
        _rollback_runtime_fence(connection)
        return terminal
    except sqlite3.Error as exc:
        _rollback_runtime_fence(connection)
        raise RuntimeProviderTrustFenceError(
            "runtime trust terminal fence SQLite operation failed"
        ) from exc
    except BaseException:
        _rollback_runtime_fence(connection)
        raise
    finally:
        connection.close()


def _production_observation_binding(
    authorization: RuntimeBoundEffectAuthorization,
    authority: ProviderObservationAuthority | None,
    ledger: ProviderObservationBindingLedger | None,
) -> tuple[ProviderObservationAuthority, ProviderObservationBindingLedger] | None:
    """Require the new contract for exact production authority.

    Non-exact authorization objects are the retained compatibility seam for
    narrow unit doubles.  They cannot be accepted by runtime-bound recovery,
    which requires an exact ``RuntimeBoundEffectAuthorization``.
    """

    if type(authorization) is not RuntimeBoundEffectAuthorization:
        if authority is not None or ledger is not None:
            if (
                type(authority) is not ProviderObservationAuthority
                or type(ledger) is not ProviderObservationBindingLedger
            ):
                raise RuntimeProviderBindingMismatch(
                    "provider observation compatibility inputs are incomplete"
                )
            return authority, ledger
        return None
    if type(authority) is not ProviderObservationAuthority:
        raise RuntimeProviderBindingMismatch(
            "exact runtime providers require ProviderObservationAuthority"
        )
    if type(ledger) is not ProviderObservationBindingLedger:
        raise RuntimeProviderBindingMismatch(
            "exact runtime providers require ProviderObservationBindingLedger"
        )
    return authority, ledger


def _prepare_observation_authority_after_start(
    *,
    spec: EntrypointSpec,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    authority: ProviderObservationAuthority,
    ledger: ProviderObservationBindingLedger,
    replay: bool,
    at: datetime,
) -> None:
    """Authenticate/load the exact binding before any provider callback."""

    try:
        if replay:
            ledger.require_bound(
                authority,
                start_receipt,
                entrypoint_id=spec.id,
                runtime_id=spec.runtime_id,
                execution=execution,
                lease_sha256=authorization.capability.lease.digest,
                source_revision=authorization.capability.source_revision,
            )
        else:
            ledger.verify_authority(
                authority,
                entrypoint_id=spec.id,
                runtime_id=spec.runtime_id,
                execution=execution,
                lease_sha256=authorization.capability.lease.digest,
                source_revision=authorization.capability.source_revision,
                at=at,
            )
            ledger.bind_start(authority, start_receipt, bound_at=at)
    except (AttributeError, ProviderObservationAuthorityError, ValueError) as exc:
        if not replay:
            _finish_or_raise_state(
                authorization,
                start_receipt,
                outcome="failed",
                detail_sha256=_exception_detail(
                    "provider-observation-authority-binding",
                    exc,
                ),
            )
        raise RuntimeProviderBindingMismatch(
            "provider observation authority could not authenticate and bind "
            "the durable start"
        ) from exc


def run_runtime_provider(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    invoke: Callable[[], T],
    output_digests: Callable[[T], Iterable[str]],
    observation_authority: ProviderObservationAuthority | None = None,
    observation_binding_ledger: ProviderObservationBindingLedger | None = None,
) -> RuntimeInvocationResult[T]:
    """Run one exact provider effect after durable grant/start authorization."""

    if not callable(invoke):
        raise TypeError("invoke must be callable")
    if not callable(output_digests):
        raise TypeError("output_digests must be callable")
    if type(execution) is not EffectExecutionRequest:
        raise RuntimeProviderBindingMismatch(
            "execution must be an exact EffectExecutionRequest"
        )
    spec = _validate_binding(entrypoint_id, authorization)
    observation_binding = _production_observation_binding(
        authorization,
        observation_authority,
        observation_binding_ledger,
    )

    authorization.grant()
    start = authorization.begin_effect(execution)
    if observation_binding is not None:
        authority, binding_ledger = observation_binding
        _prepare_observation_authority_after_start(
            spec=spec,
            authorization=authorization,
            execution=execution,
            start_receipt=start.receipt,
            authority=authority,
            ledger=binding_ledger,
            replay=not start.execute,
            at=_utc_now(),
        )
    if not start.execute:
        return RuntimeInvocationResult(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            executed=False,
            start_receipt=start.receipt,
            terminal_receipt=None,
            value=None,
        )

    try:
        value = invoke()
    except BaseException as exc:
        outcome = "cancelled" if isinstance(exc, _CANCEL_EXCEPTIONS) else "failed"
        _finish_or_raise_state(
            authorization,
            start.receipt,
            outcome=outcome,
            detail_sha256=_exception_detail("provider-invoke", exc),
        )
        raise

    try:
        authorization.verify()
    except BaseException as exc:
        _cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="post-invoke-runtime-verification",
            error=exc,
        )
        raise

    try:
        digests = _normalize_output_digests(output_digests(value))
    except BaseException as exc:
        raise RuntimeProviderReconciliationRequired(
            entrypoint_id=spec.id,
            runtime_id=spec.runtime_id,
            start_receipt=start.receipt,
            phase="output-evidence",
            cause_sha256=_exception_detail("output-evidence", exc),
        ) from exc

    try:
        authorization.verify()
    except BaseException as exc:
        _cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="pre-terminal-runtime-verification",
            error=exc,
        )
        raise

    try:
        terminal = _finish_completed_under_runtime_fence(
            authorization,
            start.receipt,
            output_digests=digests,
        )
    except RuntimeProviderTrustFenceError as exc:
        _cancel_for_trust_loss(
            authorization,
            start.receipt,
            phase="terminal-runtime-fence",
            error=exc,
        )
        raise

    return RuntimeInvocationResult(
        entrypoint_id=spec.id,
        runtime_id=spec.runtime_id,
        executed=True,
        start_receipt=start.receipt,
        terminal_receipt=terminal,
        value=value,
    )


__all__ = [
    "RuntimeInvocationResult",
    "RuntimeProviderBindingMismatch",
    "RuntimeProviderBrokerError",
    "RuntimeProviderReconciliationRequired",
    "RuntimeProviderStateError",
    "RuntimeProviderTrustFenceError",
    "run_runtime_provider",
]
