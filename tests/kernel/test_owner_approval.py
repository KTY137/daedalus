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
    ApprovalStateError,
    ConsumedOwnerApproval,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


SHA = {
    "nomination": "1" * 64,
    "candidate": "2" * 64,
    "evidence": "3" * 64,
    "target": "4" * 40,
    "base": "5" * 40,
}
SECRET = b"owner-secret-material-must-be-at-least-thirty-two-bytes"
NOW = datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="tests.owner-approval",
        source_revision=SHA["base"],
        created_at=NOW.isoformat(),
        input_digests=(
            SHA["nomination"],
            SHA["candidate"],
            SHA["evidence"],
        ),
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


def _keyring():
    return {("KTY137", "owner-key-1"): SECRET}


def _verify(approval: OwnerApproval, **expectation_changes):
    return verify_owner_approval(
        approval,
        keyring=_keyring(),
        expectation=_expectation(**expectation_changes),
        now=NOW + timedelta(seconds=1),
    )


def _ledger(path: Path, when: datetime | None = None) -> ApprovalLedger:
    instant = when or (NOW + timedelta(seconds=1))
    return ApprovalLedger(path, clock=lambda: instant)


def _consume(
    ledger: ApprovalLedger,
    approval: OwnerApproval,
    *,
    promotion_id: str = "promotion-001",
    expectation: ApprovalExpectation | None = None,
) -> ConsumedOwnerApproval:
    return ledger.consume(
        approval,
        keyring=_keyring(),
        expectation=expectation or _expectation(),
        promotion_id=promotion_id,
    )


def test_owner_approval_is_canonical_signed_and_parseable() -> None:
    approval = _approval()
    verified = _verify(approval)
    assert approval.signature_sha256 != "0" * 64
    assert OwnerApproval.from_dict(approval.to_dict()) == approval
    assert verified.approval_sha256 == approval.digest
    assert verified.nomination_receipt_sha256 == SHA["nomination"]
    assert verified.candidate_artifact_sha256 == SHA["candidate"]
    assert verified.evidence_packet_sha256 == SHA["evidence"]
    assert verified.base_revision == SHA["base"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_artifact_sha256", "a" * 64),
        ("evidence_packet_sha256", "b" * 64),
        ("nomination_receipt_sha256", "c" * 64),
        ("base_revision", "d" * 40),
        ("target_ref", "main"),
        ("current_target_revision", "e" * 40),
        ("operation", "deploy"),
    ],
)
def test_every_binding_dimension_is_fail_closed(
    field: str, value: str
) -> None:
    with pytest.raises(
        (ApprovalBindingMismatch, ValueError),
        match=field.replace("current_", "expected_") + "|operation",
    ):
        _verify(_approval(), **{field: value})


def test_tampering_unknown_keys_and_naive_time_are_rejected() -> None:
    approval = _approval()
    tampered = dataclasses.replace(approval, signature_sha256="a" * 64)
    with pytest.raises(ApprovalSignatureError, match="signature mismatch"):
        _verify(tampered)
    with pytest.raises(ApprovalSignatureError, match="unknown"):
        verify_owner_approval(
            approval,
            keyring={},
            expectation=_expectation(),
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_owner_approval(
            approval,
            keyring=_keyring(),
            expectation=_expectation(),
            now=datetime(2026, 8, 3, 7, 0),
        )


def test_expired_not_yet_valid_and_excessive_ttl_are_rejected() -> None:
    approval = _approval()
    with pytest.raises(ApprovalExpired, match="not valid yet"):
        verify_owner_approval(
            approval,
            keyring=_keyring(),
            expectation=_expectation(),
            now=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ApprovalExpired, match="expired"):
        verify_owner_approval(
            approval,
            keyring=_keyring(),
            expectation=_expectation(),
            now=NOW + timedelta(minutes=10),
        )
    with pytest.raises(ValueError, match="24-hour"):
        _approval(expires_at=(NOW + timedelta(hours=25)).isoformat())


def test_consumption_reauthenticates_signed_approval_and_retains_all_bindings(
    tmp_path,
) -> None:
    approval = _approval()
    ledger = _ledger(tmp_path / "approvals.sqlite3")
    consumed = _consume(ledger, approval)

    assert consumed.verified.approval_sha256 == approval.digest
    assert consumed.verified.nomination_receipt_sha256 == SHA["nomination"]
    assert consumed.verified.candidate_artifact_sha256 == SHA["candidate"]
    assert consumed.verified.evidence_packet_sha256 == SHA["evidence"]
    assert consumed.verified.base_revision == SHA["base"]
    assert consumed.verified.expected_target_revision == SHA["target"]
    assert consumed.expectation_sha256 == _expectation().digest
    assert ledger.verify_consumption(
        consumed, keyring=_keyring()
    ) == consumed
    assert ledger.consumed(approval.digest)


def test_publicly_constructed_verified_record_cannot_be_consumed(tmp_path) -> None:
    approval = _approval()
    forged_type = _verify(approval)
    ledger = _ledger(tmp_path / "approvals.sqlite3")
    with pytest.raises(TypeError, match="signed OwnerApproval"):
        ledger.consume(
            forged_type,  # type: ignore[arg-type]
            keyring=_keyring(),
            expectation=_expectation(),
            promotion_id="promotion-forged",
        )
    assert not ledger.consumed(approval.digest)


def test_tampered_and_wrong_expectation_fail_before_persistence(tmp_path) -> None:
    path = tmp_path / "approvals.sqlite3"
    ledger = _ledger(path)
    tampered = dataclasses.replace(_approval(), signature_sha256="a" * 64)
    with pytest.raises(ApprovalSignatureError):
        _consume(ledger, tampered)
    with pytest.raises(ApprovalBindingMismatch, match="candidate"):
        _consume(
            ledger,
            _approval(),
            expectation=_expectation(candidate_artifact_sha256="a" * 64),
        )
    with sqlite3.connect(path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM owner_approval_consumptions_v2"
        ).fetchone()[0]
    assert count == 0


def test_nonce_approval_and_promotion_id_are_consumed_once_atomically(
    tmp_path,
) -> None:
    approval = _approval()
    ledger = _ledger(tmp_path / "approvals.sqlite3")
    first = _consume(ledger, approval)
    with pytest.raises(ApprovalReplay):
        _consume(ledger, approval, promotion_id="promotion-002")

    other = _approval(approval_id="approval-002", nonce="nonce-002")
    with pytest.raises(ApprovalReplay):
        _consume(ledger, other, promotion_id=first.promotion_id)


def test_same_nonce_cannot_be_repackaged_into_another_signed_approval(
    tmp_path,
) -> None:
    first = _approval()
    second = _approval(approval_id="approval-002")
    ledger = _ledger(tmp_path / "approvals.sqlite3")
    _consume(ledger, first, promotion_id="promotion-001")
    with pytest.raises(ApprovalReplay):
        _consume(ledger, second, promotion_id="promotion-002")


def test_concurrent_consumption_allows_exactly_one_winner(tmp_path) -> None:
    approval = _approval()
    ledger = _ledger(tmp_path / "approvals.sqlite3")

    def consume(index: int) -> str:
        try:
            _consume(
                ledger,
                approval,
                promotion_id=f"promotion-{index:03d}",
            )
            return "accepted"
        except ApprovalReplay:
            return "replayed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(consume, range(16)))
    assert results.count("accepted") == 1
    assert results.count("replayed") == 15


def test_expiry_is_rechecked_inside_atomic_consumption(tmp_path) -> None:
    approval = _approval(
        expires_at=(NOW + timedelta(seconds=2)).isoformat()
    )
    instants = iter(
        (
            NOW + timedelta(seconds=1),
            NOW + timedelta(seconds=1, milliseconds=500),
            NOW + timedelta(seconds=2),
        )
    )
    ledger = ApprovalLedger(
        tmp_path / "approvals.sqlite3",
        clock=lambda: next(instants),
    )
    with pytest.raises(
        ApprovalExpired, match="expired before consumption persistence"
    ):
        _consume(ledger, approval)
    assert not ledger.consumed(approval.digest)


def test_consumption_receipt_rejects_tampering_and_unpersisted_forgery(
    tmp_path,
) -> None:
    approval = _approval()
    ledger = _ledger(tmp_path / "approvals.sqlite3")
    consumed = _consume(ledger, approval)

    with pytest.raises(ValueError, match="digest mismatch"):
        dataclasses.replace(consumed, promotion_id="promotion-other")

    payload = consumed.payload_dict()
    payload["promotion_id"] = "promotion-other"
    forged = ConsumedOwnerApproval(
        verified=consumed.verified,
        expectation_sha256=consumed.expectation_sha256,
        promotion_id="promotion-other",
        consumed_at=consumed.consumed_at,
        consumption_sha256=canonical_sha(payload),
    )
    with pytest.raises(ApprovalStateError, match="not persisted"):
        ledger.verify_consumption(forged, keyring=_keyring())


def test_corrupt_or_row_mismatched_persisted_consumption_fails_closed(
    tmp_path,
) -> None:
    approval = _approval()
    path = tmp_path / "approvals.sqlite3"
    ledger = _ledger(path)
    consumed = _consume(ledger, approval)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE owner_approval_consumptions_v2 "
            "SET consumption_json=? WHERE approval_sha256=?",
            ("{", approval.digest),
        )
    with pytest.raises(ApprovalStateError, match="corrupt"):
        ledger.verify_consumption(consumed, keyring=_keyring())

    path2 = tmp_path / "approvals-row.sqlite3"
    ledger2 = _ledger(path2)
    consumed2 = _consume(ledger2, approval)
    with sqlite3.connect(path2) as connection:
        connection.execute(
            "UPDATE owner_approval_consumptions_v2 "
            "SET capability_sha256=? WHERE approval_sha256=?",
            ("f" * 64, approval.digest),
        )
    with pytest.raises(ApprovalStateError, match="persisted authority"):
        ledger2.verify_consumption(consumed2, keyring=_keyring())


def test_corrupt_replay_ledger_and_malformed_consumed_query_fail_closed(
    tmp_path,
) -> None:
    path = tmp_path / "approvals.sqlite3"
    path.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(sqlite3.DatabaseError):
        ApprovalLedger(path)
    ledger = _ledger(tmp_path / "clean.sqlite3")
    with pytest.raises(ValueError, match="sha256"):
        ledger.consumed("not-a-digest")


def test_legacy_consumption_rows_require_explicit_migration(tmp_path) -> None:
    path = tmp_path / "approvals.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE owner_approval_consumptions (
                approval_sha256 TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO owner_approval_consumptions VALUES (?)",
            ("a" * 64,),
        )
    with pytest.raises(ApprovalStateError, match="explicit migration"):
        ApprovalLedger(path)


def test_ledger_clock_must_be_monotonic(tmp_path) -> None:
    approval = _approval()
    instants = iter(
        (
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=1),
        )
    )
    ledger = ApprovalLedger(
        tmp_path / "backwards.sqlite3",
        clock=lambda: next(instants),
    )
    with pytest.raises(ApprovalStateError, match="moved backwards"):
        _consume(ledger, approval)
    assert not ledger.consumed(approval.digest)


def test_persisted_approval_and_expectation_bytes_are_reauthenticated(
    tmp_path,
) -> None:
    approval = _approval()
    path = tmp_path / "approvals.sqlite3"
    ledger = _ledger(path)
    consumed = _consume(ledger, approval)
    with sqlite3.connect(path) as connection:
        approval_payload = json.loads(
            connection.execute(
                "SELECT approval_json FROM owner_approval_consumptions_v2"
            ).fetchone()[0]
        )
        approval_payload["candidate_artifact_sha256"] = "a" * 64
        connection.execute(
            "UPDATE owner_approval_consumptions_v2 SET approval_json=?",
            (
                json.dumps(
                    approval_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
    with pytest.raises(
        (ApprovalSignatureError, ApprovalStateError),
        match="signature mismatch|persisted authority",
    ):
        ledger.verify_consumption(consumed, keyring=_keyring())


def test_secret_strength_expiry_order_and_promotion_id_are_enforced(
    tmp_path,
) -> None:
    with pytest.raises(ValueError, match="at least 32"):
        _approval(secret=b"weak")
    with pytest.raises(ValueError, match="after issued_at"):
        _approval(expires_at=NOW.isoformat())
    ledger = _ledger(tmp_path / "approvals.sqlite3")
    with pytest.raises(ValueError, match="promotion_id"):
        _consume(ledger, _approval(), promotion_id=" invalid ")


def test_issue_and_verify_cli_are_stdout_only(
    tmp_path, monkeypatch, capsys
) -> None:
    from daedalus.kernel import approvals as module

    issued = NOW - timedelta(seconds=1)
    expires = NOW + timedelta(minutes=10)
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
            input_digests=(
                SHA["nomination"],
                SHA["candidate"],
                SHA["evidence"],
            ),
        ).to_dict(),
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_OWNER_SECRET", SECRET.decode())
    assert module._cli_issue(
        request_path, "DAEDALUS_OWNER_SECRET"
    ) == 0
    approval_payload = json.loads(capsys.readouterr().out)
    OwnerApproval.from_dict(approval_payload)

    bad_request = dict(request)
    bad_request["signature_sha256"] = "0" * 64
    bad_path = tmp_path / "bad-request.json"
    bad_path.write_text(json.dumps(bad_request), encoding="utf-8")
    with pytest.raises(ValueError, match="must not supply a signature"):
        module._cli_issue(bad_path, "DAEDALUS_OWNER_SECRET")

    expectation_path = tmp_path / "expectation.json"
    expectation_path.write_text(
        json.dumps(dataclasses.asdict(_expectation())),
        encoding="utf-8",
    )
    live_now = datetime.now(timezone.utc)
    approval = issue_owner_approval(
        approval_id="approval-cli-live",
        owner_id="KTY137",
        key_id="owner-key-1",
        operation="promote-candidate",
        nomination_receipt_sha256=SHA["nomination"],
        candidate_artifact_sha256=SHA["candidate"],
        evidence_packet_sha256=SHA["evidence"],
        base_revision=SHA["base"],
        target_ref="experimental",
        expected_target_revision=SHA["target"],
        nonce="nonce-cli-live",
        issued_at=(live_now - timedelta(seconds=1)).isoformat(),
        expires_at=(live_now + timedelta(minutes=5)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.owner-approval-cli",
            source_revision=SHA["base"],
            created_at=live_now.isoformat(),
            input_digests=(
                SHA["nomination"],
                SHA["candidate"],
                SHA["evidence"],
            ),
        ),
        secret=SECRET,
    )
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps(approval.to_dict()), encoding="utf-8"
    )
    assert module._cli_verify(
        approval_path,
        expectation_path,
        "DAEDALUS_OWNER_SECRET",
    ) == 0
    verified_payload = json.loads(capsys.readouterr().out)
    assert verified_payload["approval_sha256"] == approval.digest
    assert verified_payload["candidate_artifact_sha256"] == SHA["candidate"]
    assert set(tmp_path.iterdir()) == {
        request_path,
        bad_path,
        expectation_path,
        approval_path,
    }


def test_owner_approval_json_schema_is_closed_and_complete() -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "configs/schemas/owner-approval-v1.schema.json"
        ).read_text()
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["operation"] == {
        "const": "promote-candidate"
    }
    assert schema["properties"]["provenance"] == {
        "$ref": "#/$defs/provenance"
    }
    assert schema["$defs"]["provenance"]["additionalProperties"] is False
