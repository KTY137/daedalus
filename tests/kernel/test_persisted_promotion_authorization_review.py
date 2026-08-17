from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.approvals import (
    ApprovalLedger,
    ConsumedOwnerApproval,
    VerifiedOwnerApproval,
)
from daedalus.kernel.promotion import (
    PromotionAuthorizationError,
    authorize_persisted_promotion,
)
from daedalus.schemas import _utc_timestamp
from daedalus.spine.envelope import canonical_sha

NOW = datetime(2026, 8, 3, 18, 30, tzinfo=timezone.utc)


def _verified(*, approval_id: str) -> VerifiedOwnerApproval:
    return VerifiedOwnerApproval(
        approval_sha256=("1" if approval_id == "approval-one" else "2") * 64,
        approval_id=approval_id,
        owner_id="KTY137",
        key_id="owner-key",
        operation="promote-candidate",
        nomination_receipt_sha256="3" * 64,
        candidate_artifact_sha256="4" * 64,
        evidence_packet_sha256="5" * 64,
        base_revision="6" * 40,
        nonce=("nonce-one" if approval_id == "approval-one" else "nonce-two"),
        target_ref="experimental",
        expected_target_revision="7" * 40,
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        signature_sha256="8" * 64,
    )


def _consumed(*, approval_id: str, promotion_id: str) -> ConsumedOwnerApproval:
    verified = _verified(approval_id=approval_id)
    # ConsumedOwnerApproval normalizes consumed_at before it digests its own
    # payload, so the fixture has to digest the normalized form. Reuse the
    # contract's normalizer rather than hand-formatting, so this cannot drift
    # apart from the contract again.
    payload = {
        "verified": verified.to_dict(),
        "expectation_sha256": "9" * 64,
        "promotion_id": promotion_id,
        "consumed_at": _utc_timestamp(
            (NOW + timedelta(seconds=1)).isoformat(), "consumed_at"
        ),
    }
    return ConsumedOwnerApproval(
        verified=verified,
        expectation_sha256=payload["expectation_sha256"],
        promotion_id=promotion_id,
        consumed_at=payload["consumed_at"],
        consumption_sha256=canonical_sha(payload),
    )


def test_review_refuses_ledger_that_substitutes_another_capability(
    tmp_path,
    monkeypatch,
) -> None:
    supplied = _consumed(
        approval_id="approval-one",
        promotion_id="promotion-one",
    )
    substituted = _consumed(
        approval_id="approval-two",
        promotion_id="promotion-two",
    )
    ledger = ApprovalLedger(tmp_path / "approval.sqlite3", clock=lambda: NOW)

    def swap_receipt(_receipt, *, keyring):
        assert keyring
        return substituted

    monkeypatch.setattr(ledger, "verify_consumption", swap_receipt)

    with pytest.raises(
        PromotionAuthorizationError,
        match="different consumption capability",
    ):
        authorize_persisted_promotion(
            approval_ledger=ledger,
            owner_keyring={("KTY137", "owner-key"): b"x" * 32},
            consumed_approval=supplied,
            evidence_packet=object(),  # type: ignore[arg-type]
            candidates=(),
            target_ref="experimental",
            live_target_revision="7" * 40,
        )
