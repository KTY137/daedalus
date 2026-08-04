"""Strangler adapter composing the top-level promotion Effect Lease.

The sealed historical promotion callable remains unchanged.  This adapter
binds one exact :class:`PromotionEffectCapability`, persists its Effect-Lease
start before delegating to the existing promotion lifecycle, and appends only
the exact evidence-derived terminal after the promotion execution is durable.
Restart states never re-enter the promotion callable automatically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.promotion import (
    PromotionAuthorizationError,
    authorize_persisted_promotion,
    resolve_live_target_revision,
    snapshot_promotion_candidates,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
    PromotionReconciliationProjection,
    inspect_promotion_reconciliation,
)
from daedalus.kernel.promotion_terminalization import (
    PromotionEffectTerminalizationError,
    terminalize_promotion_effect,
)

from . import gated_writes


class PromotionEffectLifecycleError(RuntimeError):
    """The outer promotion lifecycle could not safely advance."""


def _status(
    projection: PromotionReconciliationProjection,
    *,
    terminal_replayed: bool | None = None,
) -> dict[str, Any]:
    effect = projection.effect_execution
    promotion = projection.promotion_execution
    body: dict[str, Any] = {
        "schema": "daedalus-promotion-effect-lifecycle/1",
        "disposition": projection.disposition.value,
        "automatic_execution_allowed": False,
        "effect_start_receipt_sha256": (
            None if effect is None else effect.start.receipt_sha256
        ),
        "effect_terminal_receipt_sha256": (
            None
            if effect is None or effect.terminal is None
            else effect.terminal.receipt_sha256
        ),
        "promotion_start_sha256": (
            None if promotion is None else promotion.start.digest
        ),
        "promotion_terminal_sha256": (
            None
            if promotion is None or promotion.completion is None
            else promotion.completion.receipt.digest
        ),
    }
    if terminal_replayed is not None:
        body["effect_terminal_replayed"] = terminal_replayed
    return body


def _report_with_status(
    report: Mapping[str, Any],
    projection: PromotionReconciliationProjection,
    *,
    terminal_replayed: bool | None = None,
) -> dict[str, Any]:
    result = dict(report)
    result["promotion_effect_lifecycle"] = _status(
        projection,
        terminal_replayed=terminal_replayed,
    )
    return result


def _pending_report(
    capability: PromotionEffectCapability,
    projection: PromotionReconciliationProjection,
    reason: BaseException | str,
) -> dict[str, Any]:
    message = str(reason)
    error_type = type(reason).__name__ if isinstance(reason, BaseException) else "Pending"
    return {
        "promoted": [],
        "refused": [],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": capability.promotion.to_dict(),
        "promotion_effect_pending_reconciliation": True,
        "promotion_effect_error": {
            "type": error_type,
            "message": message[:512],
        },
        "promotion_effect_lifecycle": _status(projection),
    }


def _retained_report(
    projection: PromotionReconciliationProjection,
) -> Mapping[str, Any]:
    promotion = projection.promotion_execution
    if promotion is None or promotion.completion is None:
        raise PromotionEffectLifecycleError(
            "terminal promotion lifecycle has no retained completion report"
        )
    return promotion.completion.report_dict()


def _preauthorize_exact_subject(
    *,
    repo_root: str,
    candidates: tuple[Any, ...],
    capability: PromotionEffectCapability,
    approval_ledger: Any,
    owner_keyring: Mapping[tuple[str, str], bytes | str],
    consumed_approval: Any,
    evidence_packet: Any,
    target_ref: str,
) -> None:
    try:
        root = Path(repo_root).resolve(strict=True)
        live_target_revision = resolve_live_target_revision(root, target_ref)
        snapshots = snapshot_promotion_candidates(candidates)
        observed = authorize_persisted_promotion(
            approval_ledger=approval_ledger,
            owner_keyring=owner_keyring,
            consumed_approval=consumed_approval,
            evidence_packet=evidence_packet,
            candidates=snapshots,
            target_ref=target_ref,
            live_target_revision=live_target_revision,
        )
    except Exception as exc:  # noqa: BLE001 - no effect start exists yet
        raise PromotionEffectLifecycleError(
            f"promotion effect subject preauthorization failed: {type(exc).__name__}: {exc}"
        ) from exc
    if observed.to_dict() != capability.promotion.to_dict():
        raise PromotionEffectLifecycleError(
            "promotion effect capability does not bind the submitted promotion subject"
        )


def promote_candidates_with_effect_lifecycle(
    repo_root: str,
    candidates: list[Any],
    *,
    project: str | None,
    availability: dict,
    consumed_approval: Any,
    evidence_packet: Any,
    target_ref: str,
    promotion_effect_capability: PromotionEffectCapability,
    approval_ledger: Any,
    owner_keyring: Mapping[tuple[str, str], bytes | str],
    promotion_execution_ledger: PromotionExecutionLedger,
    ledger_path: Any = None,
    lock_timeout_s: float = 120.0,
    gate_timeout_s: float = 900.0,
    cancel: Any = None,
) -> dict[str, Any]:
    """Run or replay one exact promotion under its persisted Effect Lease.

    Fresh execution performs the following ordered transitions:

    ``preauthorize → grant lease → persist effect start → sealed promotion``.

    Once the sealed promotion has a durable terminal, terminal accounting is
    derived through :func:`terminalize_promotion_effect`.  Existing pending
    starts return reconciliation state and never call promotion again.
    """

    if not isinstance(promotion_effect_capability, PromotionEffectCapability):
        raise TypeError(
            "promotion lifecycle requires PromotionEffectCapability"
        )
    if not isinstance(promotion_execution_ledger, PromotionExecutionLedger):
        raise TypeError(
            "promotion lifecycle requires PromotionExecutionLedger"
        )
    try:
        submitted = tuple(candidates)
    except TypeError as exc:
        raise PromotionEffectLifecycleError(
            "promotion candidates must be an iterable batch"
        ) from exc
    if not owner_keyring:
        raise PromotionEffectLifecycleError("owner keyring is required")

    projection = inspect_promotion_reconciliation(
        promotion_effect_capability,
        promotion_execution_ledger,
    )
    disposition = projection.disposition

    if disposition is PromotionReconciliationDisposition.COMPLETE:
        return _report_with_status(
            _retained_report(projection),
            projection,
            terminal_replayed=True,
        )
    if (
        disposition
        is PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
    ):
        try:
            terminalized = terminalize_promotion_effect(
                promotion_effect_capability,
                promotion_execution_ledger,
            )
        except PromotionEffectTerminalizationError as exc:
            return _pending_report(
                promotion_effect_capability,
                projection,
                exc,
            )
        return _report_with_status(
            _retained_report(terminalized.reconciliation),
            terminalized.reconciliation,
            terminal_replayed=terminalized.replayed,
        )
    if disposition in {
        PromotionReconciliationDisposition.EFFECT_ONLY_PENDING,
        PromotionReconciliationDisposition.PROMOTION_PENDING,
    }:
        return _pending_report(
            promotion_effect_capability,
            projection,
            "retained promotion start requires explicit reconciliation",
        )
    if disposition is not PromotionReconciliationDisposition.FRESH:
        raise PromotionEffectLifecycleError(
            "promotion effect lifecycle has an unknown disposition"
        )

    _preauthorize_exact_subject(
        repo_root=repo_root,
        candidates=submitted,
        capability=promotion_effect_capability,
        approval_ledger=approval_ledger,
        owner_keyring=owner_keyring,
        consumed_approval=consumed_approval,
        evidence_packet=evidence_packet,
        target_ref=target_ref,
    )

    promotion_effect_capability.grant()
    effect_begin = promotion_effect_capability.begin()
    if not effect_begin.execute:
        concurrent = inspect_promotion_reconciliation(
            promotion_effect_capability,
            promotion_execution_ledger,
        )
        return _pending_report(
            promotion_effect_capability,
            concurrent,
            "effect start already exists and cannot be re-executed automatically",
        )

    try:
        gated_writes.promote_candidates(
            repo_root,
            list(submitted),
            project=project,
            availability=availability,
            consumed_approval=consumed_approval,
            evidence_packet=evidence_packet,
            target_ref=target_ref,
            approval_ledger=approval_ledger,
            owner_keyring=owner_keyring,
            promotion_execution_ledger=promotion_execution_ledger,
            ledger_path=ledger_path,
            lock_timeout_s=lock_timeout_s,
            gate_timeout_s=gate_timeout_s,
            cancel=cancel,
        )
    except Exception as exc:  # noqa: BLE001 - persisted start must remain visible
        after_exception = inspect_promotion_reconciliation(
            promotion_effect_capability,
            promotion_execution_ledger,
        )
        return _pending_report(
            promotion_effect_capability,
            after_exception,
            exc,
        )

    after = inspect_promotion_reconciliation(
        promotion_effect_capability,
        promotion_execution_ledger,
    )
    if (
        after.disposition
        is PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
    ):
        try:
            terminalized = terminalize_promotion_effect(
                promotion_effect_capability,
                promotion_execution_ledger,
            )
        except PromotionEffectTerminalizationError as exc:
            return _pending_report(
                promotion_effect_capability,
                after,
                exc,
            )
        return _report_with_status(
            _retained_report(terminalized.reconciliation),
            terminalized.reconciliation,
            terminal_replayed=terminalized.replayed,
        )
    if after.disposition is PromotionReconciliationDisposition.COMPLETE:
        return _report_with_status(
            _retained_report(after),
            after,
            terminal_replayed=True,
        )
    return _pending_report(
        promotion_effect_capability,
        after,
        "promotion did not reach a terminally reconciled state",
    )


__all__ = [
    "PromotionEffectLifecycleError",
    "promote_candidates_with_effect_lifecycle",
]
