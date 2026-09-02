from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import json
import os
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
KEYRING = {("KTY137", "owner-key-1"): SECRET}
NOW = datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)


def provenance() -> ContractProvenance:
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


def approval(**changes) -> OwnerApproval:
    values = {
        "approval_id": "approval-001",
        "owner_id": "KTY137",
        "key_id": "owner-key-1",
        "operation": "promote-candidate",
        "nomination_receipt_sha256": SHA["nomination"],
        "candidate_artifact_sha256": SHA["candidate"],
        "evidence_packet_sha256": SHA["evidence"],
        "base_revision": SHA["base"],
        "target_ref": "experimental",
        "expected_target_revision": SHA["target"],
        "nonce": "nonce-001",
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
        "provenance": provenance(),
        "secret": SECRET,
    }
    values.update(changes)
    return issue_owner_approval(**values)


def expectation(**changes) -> ApprovalExpectation:
    values = {
        "operation": "promote-candidate",
        "nomination_receipt_sha256": SHA["nomination"],
        "candidate_artifact_sha256": SHA["candidate"],
        "evidence_packet_sha256": SHA["evidence"],
        "base_revision": SHA["base"],
        "target_ref": "experimental",
        "current_target_revision": SHA["target"],
    }
    values.update(changes)
    return ApprovalExpectation(**values)


def ledger(path: Path, when: datetime | None = None) -> ApprovalLedger:
    instant = when or (NOW + timedelta(seconds=1))
    return ApprovalLedger(path, clock=lambda: instant)


def consume(
    authority: ApprovalLedger,
    signed: OwnerApproval,
    *,
    promotion_id: str = "promotion-001",
    expected: ApprovalExpectation | None = None,
) -> ConsumedOwnerApproval:
    return authority.consume(
        signed,
        keyring=KEYRING,
        expectation=expected or expectation(),
        promotion_id=promotion_id,
    )


def test_signed_contract_round_trip_and_full_verified_bindings() -> None:
    signed = approval()
    verified = verify_owner_approval(
        signed,
        keyring=KEYRING,
        expectation=expectation(),
        now=NOW + timedelta(seconds=1),
    )
    assert OwnerApproval.from_dict(signed.to_dict()) == signed
    assert verified.approval_sha256 == signed.digest
    assert verified.nomination_receipt_sha256 == SHA["nomination"]
    assert verified.candidate_artifact_sha256 == SHA["candidate"]
    assert verified.evidence_packet_sha256 == SHA["evidence"]
    assert verified.base_revision == SHA["base"]
    assert verified.expected_target_revision == SHA["target"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_artifact_sha256", "a" * 64),
        ("evidence_packet_sha256", "b" * 64),
        ("nomination_receipt_sha256", "c" * 64),
        ("base_revision", "d" * 40),
        ("target_ref", "main"),
        ("current_target_revision", "e" * 40),
    ],
)
def test_every_expectation_binding_is_fail_closed(field: str, value: str) -> None:
    with pytest.raises(ApprovalBindingMismatch, match=field.replace("current_", "expected_")):
        verify_owner_approval(
            approval(),
            keyring=KEYRING,
            expectation=expectation(**{field: value}),
            now=NOW + timedelta(seconds=1),
        )


def test_signature_key_time_and_ttl_fail_closed() -> None:
    signed = approval()
    tampered = dataclasses.replace(signed, signature_sha256="a" * 64)
    with pytest.raises(ApprovalSignatureError, match="signature mismatch"):
        verify_owner_approval(
            tampered,
            keyring=KEYRING,
            expectation=expectation(),
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ApprovalSignatureError, match="unknown"):
        verify_owner_approval(
            signed,
            keyring={},
            expectation=expectation(),
            now=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_owner_approval(
            signed,
            keyring=KEYRING,
            expectation=expectation(),
            now=datetime(2026, 8, 3, 7, 0),
        )
    with pytest.raises(ApprovalExpired, match="not valid yet"):
        verify_owner_approval(
            signed,
            keyring=KEYRING,
            expectation=expectation(),
            now=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ApprovalExpired, match="expired"):
        verify_owner_approval(
            signed,
            keyring=KEYRING,
            expectation=expectation(),
            now=NOW + timedelta(minutes=10),
        )
    with pytest.raises(ValueError, match="24-hour"):
        approval(expires_at=(NOW + timedelta(hours=25)).isoformat())


def test_consumption_reauthenticates_and_persists_all_bindings(tmp_path) -> None:
    signed = approval()
    authority = ledger(tmp_path / "approvals.sqlite3")
    receipt = consume(authority, signed)
    assert receipt.verified.approval_sha256 == signed.digest
    assert receipt.verified.candidate_artifact_sha256 == SHA["candidate"]
    assert receipt.verified.evidence_packet_sha256 == SHA["evidence"]
    assert receipt.verified.base_revision == SHA["base"]
    assert receipt.expectation_sha256 == expectation().digest
    assert authority.verify_consumption(receipt, keyring=KEYRING) == receipt
    assert authority.consumed(signed.digest)


def test_constructed_verified_record_cannot_cross_consumption_boundary(tmp_path) -> None:
    signed = approval()
    verified = verify_owner_approval(
        signed,
        keyring=KEYRING,
        expectation=expectation(),
        now=NOW + timedelta(seconds=1),
    )
    authority = ledger(tmp_path / "approvals.sqlite3")
    with pytest.raises(TypeError, match="signed OwnerApproval"):
        authority.consume(
            verified,  # type: ignore[arg-type]
            keyring=KEYRING,
            expectation=expectation(),
            promotion_id="promotion-forged",
        )
    assert not authority.consumed(signed.digest)


def test_tampered_signature_or_wrong_expectation_leaves_no_row(tmp_path) -> None:
    path = tmp_path / "approvals.sqlite3"
    authority = ledger(path)
    with pytest.raises(ApprovalSignatureError):
        consume(
            authority,
            dataclasses.replace(approval(), signature_sha256="a" * 64),
        )
    with pytest.raises(ApprovalBindingMismatch, match="candidate"):
        consume(
            authority,
            approval(),
            expected=expectation(candidate_artifact_sha256="a" * 64),
        )
    with contextlib.closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM owner_approval_consumptions_v2"
        ).fetchone()[0] == 0


def test_replay_nonce_and_promotion_identity_are_unique(tmp_path) -> None:
    authority = ledger(tmp_path / "approvals.sqlite3")
    first = approval()
    receipt = consume(authority, first)
    with pytest.raises(ApprovalReplay):
        consume(authority, first, promotion_id="promotion-002")
    with pytest.raises(ApprovalReplay):
        consume(
            authority,
            approval(approval_id="approval-002"),
            promotion_id="promotion-002",
        )
    with pytest.raises(ApprovalReplay):
        consume(
            authority,
            approval(approval_id="approval-003", nonce="nonce-003"),
            promotion_id=receipt.promotion_id,
        )


def test_concurrent_consumption_has_exactly_one_winner(tmp_path) -> None:
    authority = ledger(tmp_path / "approvals.sqlite3")
    signed = approval()

    def run(index: int) -> str:
        try:
            consume(authority, signed, promotion_id=f"promotion-{index:03d}")
            return "accepted"
        except ApprovalReplay:
            return "replayed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(16)))
    assert results.count("accepted") == 1
    assert results.count("replayed") == 15


def test_expiry_is_rechecked_at_persistence(tmp_path) -> None:
    signed = approval(expires_at=(NOW + timedelta(seconds=2)).isoformat())
    instants = iter(
        (
            NOW + timedelta(seconds=1),
            NOW + timedelta(seconds=1, milliseconds=500),
            NOW + timedelta(seconds=2),
        )
    )
    authority = ApprovalLedger(
        tmp_path / "approvals.sqlite3",
        clock=lambda: next(instants),
    )
    with pytest.raises(ApprovalExpired, match="expired before consumption persistence"):
        consume(authority, signed)
    assert not authority.consumed(signed.digest)


def test_ledger_clock_must_be_monotonic(tmp_path) -> None:
    instants = iter(
        (
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=1),
        )
    )
    authority = ApprovalLedger(
        tmp_path / "approvals.sqlite3",
        clock=lambda: next(instants),
    )
    with pytest.raises(ApprovalStateError, match="moved backwards"):
        consume(authority, approval())


def test_receipt_tampering_and_unpersisted_forgery_fail_closed(tmp_path) -> None:
    authority = ledger(tmp_path / "approvals.sqlite3")
    receipt = consume(authority, approval())
    with pytest.raises(ValueError, match="digest mismatch"):
        dataclasses.replace(receipt, promotion_id="promotion-other")

    payload = receipt.payload_dict()
    payload["promotion_id"] = "promotion-other"
    forged = ConsumedOwnerApproval(
        verified=receipt.verified,
        expectation_sha256=receipt.expectation_sha256,
        promotion_id="promotion-other",
        consumed_at=receipt.consumed_at,
        consumption_sha256=canonical_sha(payload),
    )
    with pytest.raises(ApprovalStateError, match="not persisted"):
        authority.verify_consumption(forged, keyring=KEYRING)


def test_corrupt_consumption_and_row_mismatch_fail_closed(tmp_path) -> None:
    signed = approval()
    corrupt_path = tmp_path / "corrupt.sqlite3"
    corrupt = ledger(corrupt_path)
    receipt = consume(corrupt, signed)
    with contextlib.closing(sqlite3.connect(corrupt_path)) as connection:
        connection.execute(
            "UPDATE owner_approval_consumptions_v2 SET consumption_json=?",
            ("{",),
        )
        connection.commit()
    with pytest.raises(ApprovalStateError, match="corrupt"):
        corrupt.verify_consumption(receipt, keyring=KEYRING)

    mismatch_path = tmp_path / "mismatch.sqlite3"
    mismatch = ledger(mismatch_path)
    receipt2 = consume(mismatch, signed)
    with contextlib.closing(sqlite3.connect(mismatch_path)) as connection:
        connection.execute(
            "UPDATE owner_approval_consumptions_v2 SET capability_sha256=?",
            ("f" * 64,),
        )
        connection.commit()
    with pytest.raises(ApprovalStateError, match="persisted authority"):
        mismatch.verify_consumption(receipt2, keyring=KEYRING)


def test_persisted_approval_and_expectation_bytes_are_reauthenticated(tmp_path) -> None:
    signed = approval()
    path = tmp_path / "approvals.sqlite3"
    authority = ledger(path)
    receipt = consume(authority, signed)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        stored = json.loads(
            connection.execute(
                "SELECT approval_json FROM owner_approval_consumptions_v2"
            ).fetchone()[0]
        )
        stored["candidate_artifact_sha256"] = "a" * 64
        connection.execute(
            "UPDATE owner_approval_consumptions_v2 SET approval_json=?",
            (json.dumps(stored, sort_keys=True, separators=(",", ":")),),
        )
        connection.commit()
    with pytest.raises(
        (ApprovalSignatureError, ApprovalStateError),
        match="signature mismatch|persisted authority|corrupt",
    ):
        authority.verify_consumption(receipt, keyring=KEYRING)


def test_nonempty_legacy_authority_requires_explicit_migration(tmp_path) -> None:
    path = tmp_path / "approvals.sqlite3"
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE owner_approval_consumptions (approval_sha256 TEXT)"
        )
        connection.execute(
            "INSERT INTO owner_approval_consumptions VALUES (?)",
            ("a" * 64,),
        )
        connection.commit()
    with pytest.raises(ApprovalStateError, match="explicit migration"):
        ApprovalLedger(path)


def test_malformed_ledger_queries_and_inputs_fail_closed(tmp_path) -> None:
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(sqlite3.DatabaseError):
        ApprovalLedger(path)
    authority = ledger(tmp_path / "clean.sqlite3")
    with pytest.raises(ValueError, match="sha256"):
        authority.consumed("not-a-digest")
    with pytest.raises(ValueError, match="promotion_id"):
        consume(authority, approval(), promotion_id=" invalid ")
    with pytest.raises(ValueError, match="at least 32"):
        approval(secret=b"weak")
    with pytest.raises(ValueError, match="after issued_at"):
        approval(expires_at=NOW.isoformat())


def test_issue_and_verify_cli_are_stdout_only(tmp_path, monkeypatch, capsys) -> None:
    from daedalus.kernel import approvals as module

    live_now = datetime.now(timezone.utc)
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
        "issued_at": (live_now - timedelta(seconds=1)).isoformat(),
        "expires_at": (live_now + timedelta(minutes=5)).isoformat(),
        "provenance": ContractProvenance(
            origin="tests.owner-approval-cli",
            source_revision=SHA["base"],
            created_at=live_now.isoformat(),
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
    assert module._cli_issue(request_path, "DAEDALUS_OWNER_SECRET") == 0
    signed_payload = json.loads(capsys.readouterr().out)
    signed = OwnerApproval.from_dict(signed_payload)

    bad = dict(request)
    bad["signature_sha256"] = "0" * 64
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="must not supply a signature"):
        module._cli_issue(bad_path, "DAEDALUS_OWNER_SECRET")

    expectation_path = tmp_path / "expectation.json"
    expectation_path.write_text(
        json.dumps(dataclasses.asdict(expectation())),
        encoding="utf-8",
    )
    signed_path = tmp_path / "approval.json"
    signed_path.write_text(json.dumps(signed.to_dict()), encoding="utf-8")
    assert module._cli_verify(
        signed_path,
        expectation_path,
        "DAEDALUS_OWNER_SECRET",
    ) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["approval_sha256"] == signed.digest
    assert verified["candidate_artifact_sha256"] == SHA["candidate"]
    assert set(tmp_path.iterdir()) == {
        request_path,
        bad_path,
        expectation_path,
        signed_path,
    }


def test_owner_approval_json_schema_is_closed_and_complete() -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "configs/schemas/owner-approval-v1.schema.json"
        ).read_text()
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["operation"] == {"const": "promote-candidate"}
    assert schema["properties"]["provenance"] == {"$ref": "#/$defs/provenance"}
    assert schema["$defs"]["provenance"]["additionalProperties"] is False


def _sqlite_is_open(db) -> tuple[bool, bool]:
    """Return ``(companion_present, handle_open)`` for a SQLite database.

    ``-wal``/``-shm`` companions exist exactly while a connection is open; on
    Windows an open SQLite handle additionally blocks renaming the database
    file. The second detector is journal-mode independent.
    """

    database = Path(db)
    companion = Path(f"{database}-wal").exists() or Path(f"{database}-shm").exists()
    moved = database.with_suffix(database.suffix + ".rename-probe")
    try:
        os.rename(database, moved)
    except OSError:
        return companion, True
    os.rename(moved, database)
    return companion, False


def test_every_approval_ledger_connection_is_closed_and_consumption_commits(
    tmp_path,
) -> None:
    """The approval ledger must not leave connections to the collector.

    ``_initialize``, ``verify_consumption`` and ``consumed`` used
    ``with self._connect() as connection``. For sqlite3 that is a TRANSACTION
    scope, not a closing scope: it commits and does not close. The leaked
    connection was unreachable garbage held in a reference cycle, so it was
    finalized by the generational collector at an unpredictable moment rather
    than by refcounting at method exit, giving this store's ``-wal``/``-shm``
    companions an indeterminate lifetime.

    MEASURED on the pre-fix tree: after ``ApprovalLedger(...)`` the ``-wal``
    companion existed and the database file was still locked; after
    ``gc.collect()`` both were gone.

    Deliberately no ``gc.collect()`` before the assertions: collecting first
    finalizes the leaked connection and makes this test pass against the
    unfixed code, which is exactly how this defect class stayed hidden.

    ``consume`` is included as a control. It already used try/finally, so it
    was never leaking, and it is the write path whose commit must still land.
    """

    database = tmp_path / "approvals.sqlite3"
    signed = approval()

    authority = ledger(database)
    assert _sqlite_is_open(database) == (False, False), "_initialize leaked"

    receipt = consume(authority, signed)
    assert _sqlite_is_open(database) == (False, False), "consume leaked"

    assert authority.verify_consumption(receipt, keyring=KEYRING) == receipt
    assert _sqlite_is_open(database) == (False, False), "verify_consumption leaked"

    assert authority.consumed(signed.digest)
    assert _sqlite_is_open(database) == (False, False), "consumed leaked"

    # The consumption COMMIT survived every explicit close, and is visible to a
    # ledger instance that never owned the writing connection.
    reopened = ledger(database)
    assert reopened.consumed(signed.digest)
    assert reopened.verify_consumption(receipt, keyring=KEYRING) == receipt
