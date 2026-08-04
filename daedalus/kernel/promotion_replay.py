"""Read-only restart projection for persisted promotion execution.

The live promotion seam already persists one ``PromotionExecutionStart`` before
repository mutation and one terminal receipt afterwards.  Replaying its public
``begin`` method requires a caller-supplied primary-checkout fingerprint and can
create a missing start.  A top-level Effect-Lease replay must not do either.

This module therefore exposes one package-internal, read-only projection over an
already-open canonical ``PromotionExecutionLedger``.  It reuses the ledger's
strict persisted-event decoders, binds the retained start to the complete
``PromotionAuthorization`` and returns the existing begin-result type with
``execute=False``.  It never opens a ledger, records an intent, completes an
intent, invokes Git or performs promotion.
"""
from __future__ import annotations

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_execution import (
    PromotionExecutionBeginResult,
    PromotionExecutionLedger,
    PromotionExecutionStateError,
    _authorization_payload,
)


class PromotionReplayProjectionMismatch(PromotionExecutionStateError):
    """Persisted promotion material belongs to another authorization subject."""


def inspect_promotion_execution(
    ledger: PromotionExecutionLedger,
    authorization: PromotionAuthorization,
) -> PromotionExecutionBeginResult | None:
    """Return an exact persisted promotion start/terminal without writing.

    ``None`` means the canonical Event Store contains no start for the supplied
    promotion identity.  A retained start returns ``execute=False`` and either a
    terminal completion or ``pending_reconciliation=True``.  Any changed
    authorization field fails closed before retained report material is exposed.
    """

    if not isinstance(ledger, PromotionExecutionLedger):
        raise TypeError("promotion replay inspection requires PromotionExecutionLedger")
    expected = _authorization_payload(authorization)
    intent = ledger._intent_for(expected["promotion_id"])
    if intent is None:
        return None

    start = ledger._decode_start(intent)
    comparisons = {
        "promotion_id": (start.promotion_id, expected["promotion_id"]),
        "authorization_sha256": (
            start.authorization_sha256,
            expected["authorization_sha256"],
        ),
        "approval_consumption_sha256": (
            start.approval_consumption_sha256,
            expected["approval_consumption_sha256"],
        ),
        "candidate_artifact_sha256": (
            start.candidate_artifact_sha256,
            expected["candidate_artifact_sha256"],
        ),
        "evidence_packet_sha256": (
            start.evidence_packet_sha256,
            expected["evidence_packet_sha256"],
        ),
        "source_revision": (start.source_revision, expected["source_revision"]),
        "target_ref": (start.target_ref, expected["target_ref"]),
        "authorized_target_revision": (
            start.authorized_target_revision,
            expected["live_target_revision"],
        ),
    }
    mismatches = sorted(
        name for name, (actual, wanted) in comparisons.items() if actual != wanted
    )
    if mismatches:
        raise PromotionReplayProjectionMismatch(
            "persisted promotion start contradicts authorization: "
            + ", ".join(mismatches)
        )

    completion = ledger._decode_completion(intent, start)
    return PromotionExecutionBeginResult(
        start=start,
        execute=False,
        completion=completion,
    )


__all__ = [
    "PromotionReplayProjectionMismatch",
    "inspect_promotion_execution",
]
