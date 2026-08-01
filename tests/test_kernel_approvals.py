from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.approvals import NominationReceipt, OwnerApproval, PromotionReceipt, validate_owner_approval
from daedalus.schemas import ContractProvenance

BASE = "1" * 40
TARGET = "2" * 40
RESULT = "3" * 40
CANDIDATE = "a" * 64
EVIDENCE = "b" * 64


def ts(minutes=0):
    return (datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="microseconds")


def prov(*inputs):
    return ContractProvenance(origin="owner-test", source_revision=BASE, created_at=ts(), input_digests=inputs)


def nomination(candidate=CANDIDATE):
    return NominationReceipt(
        nomination_id="nom-1", candidate_sha256=candidate, evidence_packet_sha256=EVIDENCE,
        base_head=BASE, expected_target_head=TARGET, nominated_at=ts(),
        provenance=prov(candidate, EVIDENCE),
    )


def approval(nom=None):
    nom = nom or nomination()
    return OwnerApproval(
        approval_id="approval-1", owner_id="repository-owner", nomination_sha256=nom.digest,
        candidate_sha256=CANDIDATE, evidence_packet_sha256=EVIDENCE, base_head=BASE,
        expected_target_head=TARGET, operation="promote-candidate", nonce="nonce-1",
        issued_at=ts(), expires_at=ts(30), provenance=prov(nom.digest, CANDIDATE, EVIDENCE),
    )


def check(value, nom=None, **overrides):
    args = dict(nomination=nom or nomination(), candidate_sha256=CANDIDATE,
                evidence_packet_sha256=EVIDENCE, base_head=BASE,
                current_target_head=TARGET, now=ts(5))
    args.update(overrides)
    validate_owner_approval(value, **args)


def test_round_trip_and_exact_validation():
    nom = nomination()
    value = approval(nom)
    parsed = OwnerApproval.from_dict(value.to_dict())
    assert parsed == value
    assert parsed.digest == value.digest
    check(parsed, nom)


@pytest.mark.parametrize("key,value,match", [
    ("candidate_sha256", "c" * 64, "candidate"),
    ("evidence_packet_sha256", "d" * 64, "evidence"),
    ("base_head", "4" * 40, "base_head"),
    ("current_target_head", "5" * 40, "target_head"),
])
def test_mismatches_fail_closed(key, value, match):
    nom = nomination()
    with pytest.raises(PermissionError, match=match):
        check(approval(nom), nom, **{key: value})


def test_expiry_future_and_nonce_replay_fail_closed():
    nom = nomination()
    value = approval(nom)
    with pytest.raises(PermissionError, match="expired"):
        check(value, nom, now=ts(30))
    with pytest.raises(PermissionError, match="not_yet_valid"):
        check(value, nom, now=ts(-1))
    with pytest.raises(PermissionError, match="nonce_reused"):
        check(value, nom, consumed_nonces={value.nonce})


def test_stale_nomination_and_unknown_operation_are_refused():
    current = nomination()
    stale = nomination("c" * 64)
    with pytest.raises(PermissionError, match="nomination"):
        check(approval(stale), current)
    payload = approval().to_dict()
    payload["operation"] = "merge-unbound"
    with pytest.raises(ValueError, match="operation"):
        OwnerApproval.from_dict(payload)


def test_promotion_receipt_binds_all_critical_inputs():
    value = approval()
    receipt = PromotionReceipt(
        promotion_id="promotion-1", approval_sha256=value.digest, owner_id=value.owner_id,
        nonce=value.nonce, candidate_sha256=CANDIDATE, evidence_packet_sha256=EVIDENCE,
        base_head=BASE, previous_target_head=TARGET, resulting_target_head=RESULT,
        promoted_at=ts(10), provenance=prov(value.digest, CANDIDATE, EVIDENCE),
    )
    assert PromotionReceipt.from_dict(receipt.to_dict()) == receipt
    payload = receipt.to_dict()
    payload["resulting_target_head"] = TARGET
    with pytest.raises(ValueError, match="changed target head"):
        PromotionReceipt.from_dict(payload)
