from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.approvals import (
    ApprovalBindingMismatch,
    ApprovalExpired,
    ApprovalExpectation,
    ApprovalLedger,
    ApprovalReplay,
    ApprovalSignatureError,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import ContractProvenance

SHA = {
    "nomination": "1" * 64,
    "candidate": "2" * 64,
    "evidence": "3" * 64,
    "target": "4" * 40,
    "base": "5" * 40,
}
SECRET = b"owner-secret-material-must-be-at-least-thirty-two-bytes"
NOW = datetime(2026, 8, 1, 20, 0, tzinfo=timezone.utc)
ALLOWED_OPERATIONS = (
    "close-gate-2",
    "promote-candidate",
    "review-corpus-repository",
)


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="tests.owner-approval",
        source_revision=SHA["base"],
        created_at=NOW.isoformat(),
        input_digests=(SHA["nomination"], SHA["candidate"], SHA["evidence"]),
    )


def _approval(**changes) -> OwnerApproval:
    values = dict(
        approval_id="approval-001",
        owner_id="KTY137",
        key_id="owner-key-1",
        operation="promote-candidate",
        nomination_receipt_sha256=SHA["nomination"],
        candidate_artifact_sha256=SHA["candidate"],
        evidence_packet_sha256=SHA["evidence"],
        base_revision=SHA["base"],
        target_ref="experimental",
        expected_target_revision=SHA["target"],
        nonce="nonce-001",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=_provenance(),
        secret=SECRET,
    )
    values.update(changes)
    return issue_owner_approval(**values)


def _expectation(**changes) -> ApprovalExpectation:
    values = dict(
        operation="promote-candidate",
        nomination_receipt_sha256=SHA["nomination"],
        candidate_artifact_sha256=SHA["candidate"],
        evidence_packet_sha256=SHA["evidence"],
        base_revision=SHA["base"],
        target_ref="experimental",
        current_target_revision=SHA["target"],
    )
    values.update(changes)
    return ApprovalExpectation(**values)


def _verify(approval: OwnerApproval, **expectation_changes):
    return verify_owner_approval(
        approval,
        keyring={("KTY137", "owner-key-1"): SECRET},
        expectation=_expectation(**expectation_changes),
        now=NOW + timedelta(seconds=1),
    )


def test_owner_approval_is_canonical_signed_and_parseable() -> None:
    approval = _approval()
    assert approval.signature_sha256 != "0" * 64
    assert OwnerApproval.from_dict(approval.to_dict()) == approval
    assert _verify(approval).approval_sha256 == approval.digest


@pytest.mark.parametrize("operation", ALLOWED_OPERATIONS)
def test_every_allowlisted_owner_decision_uses_the_same_authenticated_authority(operation: str) -> None:
    approval = _approval(operation=operation)
    verified = verify_owner_approval(
        approval,
        keyring={("KTY137", "owner-key-1"): SECRET},
        expectation=_expectation(operation=operation),
        now=NOW + timedelta(seconds=1),
    )
    assert verified.operation == operation


def test_unknown_owner_decision_operation_refuses_at_contract_construction() -> None:
    with pytest.raises(ValueError, match="operation must be one of"):
        _approval(operation="deploy")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_artifact_sha256", "a" * 64),
        ("evidence_packet_sha256", "b" * 64),
        ("nomination_receipt_sha256", "c" * 64),
        ("base_revision", "d" * 40),
        ("target_ref", "main"),
        ("current_target_revision", "e" * 40),
        ("operation", "close-gate-2"),
    ],
)
def test_every_binding_dimension_is_fail_closed(field: str, value: str) -> None:
    with pytest.raises(ApprovalBindingMismatch, match=field.replace("current_", "expected_")):
        _verify(_approval(), **{field: value})


def test_tampering_and_unknown_keys_are_rejected() -> None:
    approval = _approval()
    with pytest.raises(ApprovalSignatureError, match="signature mismatch"):
        _verify(dataclasses.replace(approval, signature_sha256="a" * 64))
    with pytest.raises(ApprovalSignatureError, match="unknown"):
        verify_owner_approval(
            approval,
            keyring={},
            expectation=_expectation(),
            now=NOW + timedelta(seconds=1),
        )


def test_expired_and_not_yet_valid_are_rejected() -> None:
    approval = _approval()
    keyring = {("KTY137", "owner-key-1"): SECRET}
    with pytest.raises(ApprovalExpired, match="not valid yet"):
        verify_owner_approval(approval, keyring=keyring, expectation=_expectation(), now=NOW - timedelta(seconds=1))
    with pytest.raises(ApprovalExpired, match="expired"):
        verify_owner_approval(approval, keyring=keyring, expectation=_expectation(), now=NOW + timedelta(minutes=10))


def test_nonce_and_approval_are_consumed_once_atomically(tmp_path) -> None:
    verified = _verify(_approval())
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    first = ledger.consume(verified, promotion_id="promotion-001", consumed_at=NOW)
    assert first.verified == verified
    assert ledger.consumed(verified.approval_sha256)
    with pytest.raises(ApprovalReplay):
        ledger.consume(verified, promotion_id="promotion-002", consumed_at=NOW)


def test_same_nonce_cannot_be_repackaged_into_another_approval(tmp_path) -> None:
    first = _verify(_approval())
    second = _verify(_approval(approval_id="approval-002"))
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    ledger.consume(first, promotion_id="promotion-001", consumed_at=NOW)
    with pytest.raises(ApprovalReplay):
        ledger.consume(second, promotion_id="promotion-002", consumed_at=NOW)


def test_secret_strength_expiry_order_and_consumption_expiry_are_enforced(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least 32"):
        _approval(secret=b"weak")
    with pytest.raises(ValueError, match="after issued_at"):
        _approval(expires_at=NOW.isoformat())
    verified = _verify(_approval())
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    with pytest.raises(ApprovalExpired, match="expired before consumption"):
        ledger.consume(verified, promotion_id="promotion-expired", consumed_at=NOW + timedelta(minutes=10))
    assert not ledger.consumed(verified.approval_sha256)


def test_concurrent_consumption_allows_exactly_one_winner(tmp_path) -> None:
    verified = _verify(_approval())
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")

    def consume(index: int) -> str:
        try:
            ledger.consume(verified, promotion_id=f"promotion-{index:03d}", consumed_at=NOW)
            return "accepted"
        except ApprovalReplay:
            return "replayed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(consume, range(16)))
    assert results.count("accepted") == 1
    assert results.count("replayed") == 15


def test_corrupt_replay_ledger_fails_closed(tmp_path) -> None:
    path = tmp_path / "approvals.sqlite3"
    path.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(Exception):
        ApprovalLedger(path)


def test_consumption_digest_is_persisted_and_promotion_id_is_bounded(tmp_path) -> None:
    verified = _verify(_approval())
    path = tmp_path / "approvals.sqlite3"
    ledger = ApprovalLedger(path)
    consumed = ledger.consume(verified, promotion_id="promotion-001", consumed_at=NOW)
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT capability_sha256, consumption_sha256 FROM owner_approval_consumptions"
        ).fetchone()
    assert row == (verified.digest, consumed.consumption_sha256)
    other = _verify(_approval(approval_id="approval-002", nonce="nonce-002"))
    with pytest.raises(ValueError, match="promotion_id"):
        ledger.consume(other, promotion_id=" invalid ", consumed_at=NOW)


def test_issue_and_verify_cli_are_stdout_only(tmp_path, monkeypatch, capsys) -> None:
    from daedalus.kernel import approvals as module

    issued = datetime.now(timezone.utc) - timedelta(seconds=1)
    expires = issued + timedelta(minutes=5)
    request = {
        "contract_type": "daedalus.owner-approval",
        "contract_version": "1.0.0",
        "approval_id": "approval-cli",
        "owner_id": "KTY137",
        "key_id": "owner-key-1",
        "operation": "promote-candidate",
        "nomination_receipt_sha256": SHA["nomination"],
        "candidate_artifact_sha256": SHA["candidate"],
        "evidence_packet_sha256": SHA["evidence"],
        "base_revision": SHA["base"],
        "target_ref": "experimental",
        "expected_target_revision": SHA["target"],
        "nonce": "nonce-cli",
        "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
        "provenance": ContractProvenance(
            origin="tests.owner-approval-cli",
            source_revision=SHA["base"],
            created_at=issued.isoformat(),
            input_digests=(SHA["nomination"], SHA["candidate"], SHA["evidence"]),
        ).to_dict(),
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_OWNER_SECRET", SECRET.decode())
    assert module._cli_issue(request_path, "DAEDALUS_OWNER_SECRET") == 0
    approval = OwnerApproval.from_dict(json.loads(capsys.readouterr().out))

    expectation_path = tmp_path / "expectation.json"
    expectation_path.write_text(json.dumps(dataclasses.asdict(_expectation())), encoding="utf-8")
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(json.dumps(approval.to_dict()), encoding="utf-8")
    assert module._cli_verify(approval_path, expectation_path, "DAEDALUS_OWNER_SECRET") == 0
    assert json.loads(capsys.readouterr().out)["approval_sha256"] == approval.digest
    assert set(tmp_path.iterdir()) == {request_path, expectation_path, approval_path}


def test_owner_approval_json_schema_is_closed_complete_and_allowlisted() -> None:
    schema = json.loads((Path(__file__).resolve().parents[2] / "configs/schemas/owner-approval-v1.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["operation"] == {"enum": list(ALLOWED_OPERATIONS)}
    assert schema["properties"]["provenance"] == {"$ref": "#/$defs/provenance"}
    assert schema["$defs"]["provenance"]["additionalProperties"] is False
