"""Execute one runtime provider call behind persisted runtime and effect authority.

This module is deliberately provider-neutral. It composes the existing
``RuntimeBoundEffectAuthorization`` with one exact ``EffectExecutionRequest``
and a zero-argument provider callable. The broker persists the lease grant and
start receipt before invoking external code, makes exact replay inert, and
persists a terminal receipt for success, failure, cancellation, or runtime-trust
loss.

A successful terminal receipt is written while the exact runtime-trust row is
held under the trust ledger's SQLite writer transaction. Quarantine, expiry
persistence, or runtime rotation therefore cannot interleave between the last
trust observation and the durable ``COMPLETED`` receipt. This is a narrow
cross-ledger serialization fence, not a distributed transaction: the trust row
is read-only during the fence and the effect ledger remains the terminal-state
authority.

It does not make an existing provider safe merely by existing. A production
provider row may move to ``CENTRAL`` only after its public call path requires
this broker, produces content-addressed output evidence, and has no direct
effectful bypass.
"""
from __future__ import annotations

import re
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
    """Runtime trust changed before a successful terminal receipt was durable."""


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
    if isinstance(registry, Mapping):
        rows = dict(registry)
        if any(key != row.id for key, row in rows.items()):
            raise RuntimeProviderBindingMismatch(
                "runtime authorization registry contains mismatched key/id rows"
            )
        return rows
    rows = tuple(registry)
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
    comparisons = {
        "request entrypoint": authorization.request.entrypoint_id,
        "lease entrypoint": authorization.capability.lease.entrypoint_id,
    }
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
    """Return a non-secret deterministic exception-class digest."""

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


def _runtime_fence_components(authorization: RuntimeBoundEffectAuthorization):
    """Return the concrete trust-ledger seam, or ``None`` for narrow test doubles.

    Production ``RuntimeBoundEffectAuthorization`` objects always carry the
    persisted trust ledger and the exact runtime capability. The fallback keeps
    the broker's provider-neutral unit doubles small; the dedicated SQLite fence
    tests exercise the concrete path.
    """

    ledger = getattr(authorization, "runtime_trust_ledger", None)
    capability = getattr(authorization, "capability", None)
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
        ledger is None
        or capability is None
        or not callable(connect)
        or not callable(from_row)
        or any(not hasattr(capability, name) for name in required)
    ):
        return None
    return ledger, capability


def _finish_completed_under_runtime_fence(
    authorization: RuntimeBoundEffectAuthorization,
    start_receipt: LeasedEffectStartReceipt,
    *,
    output_digests: tuple[str, ...],
) -> EffectTerminalReceipt:
    """Persist ``COMPLETED`` while quarantine/rotation is serialized out.

    Both runtime admission/quarantine and this fence use ``BEGIN IMMEDIATE`` on
    the same trust database. Whichever boundary acquires the writer transaction
    first establishes the order: a prior quarantine is observed and completion
    is refused; a completion that already owns the fence becomes durable before
    a later quarantine can commit.
    """

    components = _runtime_fence_components(authorization)
    if components is None:
        return _finish_or_raise_state(
            authorization,
            start_receipt,
            outcome="completed",
            output_digests=output_digests,
        )

    ledger, capability = components
    connection = ledger._connect()  # noqa: SLF001 - same persisted authority seam
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
            record = ledger._from_row(row)  # noqa: SLF001 - authenticates persisted row
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
        try:
            connection.execute("COMMIT")
        except BaseException as exc:
            raise RuntimeProviderStateError(
                "runtime trust terminal fence could not be committed"
            ) from exc
        return terminal
    except BaseException:
        if connection.in_transaction:
            try:
                connection.execute("ROLLBACK")
            except BaseException:
                pass
        raise
    finally:
        connection.close()


def run_runtime_provider(
    entrypoint_id: str,
    *,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    invoke: Callable[[], T],
    output_digests: Callable[[T], Iterable[str]],
) -> RuntimeInvocationResult[T]:
    """Run one exact provider effect after durable grant/start authorization.

    ``invoke`` receives no authority object and is called only after the exact
    lease grant and start receipt exist. Reusing the same execution identity
    returns ``executed=False`` and never calls the provider a second time. Every
    successful execution must produce at least one content-addressed output
    digest before its value can be released.
    """

    if not callable(invoke):
        raise TypeError("invoke must be callable")
    if not callable(output_digests):
        raise TypeError("output_digests must be callable")
    spec = _validate_binding(entrypoint_id, authorization)

    # Grant is exact-replay idempotent. Keeping it inside the broker prevents a
    # provider adapter from accidentally starting against an unpersisted lease.
    authorization.grant()
    start = authorization.begin_effect(execution)
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

    # Runtime evidence may expire or be quarantined while a long provider call
    # is running. The effect cannot be undone, but its output is withheld and
    # the durable execution is not represented as successfully completed.
    try:
        authorization.verify(now=_utc_now())
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
        _finish_or_raise_state(
            authorization,
            start.receipt,
            outcome="failed",
            detail_sha256=_exception_detail("output-evidence", exc),
        )
        raise

    # Evidence extraction can be non-trivial. Recheck once more before entering
    # the terminal fence. The fence then authenticates the exact row again while
    # holding the trust ledger's writer transaction through effect completion.
    try:
        authorization.verify(now=_utc_now())
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
    "RuntimeProviderStateError",
    "RuntimeProviderTrustFenceError",
    "run_runtime_provider",
]
