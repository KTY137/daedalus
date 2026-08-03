from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from daedalus.kernel.runtime_conformance import RuntimeConformanceError
from daedalus.runtimes import (
    RuntimeTrustBindingMismatch,
    RuntimeTrustCorrupt,
    RuntimeTrustExpired,
    RuntimeTrustLedger,
    RuntimeTrustQuarantined,
)

NOW = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
REVISION = "1" * 40
_DIGESTS = {
    "first": ("a" * 64, "b" * 64, "c" * 64, "d" * 64),
    "second": ("5" * 64, "6" * 64, "7" * 64, "8" * 64),
    "stale": ("9" * 64, "0" * 64, "e" * 64, "f" * 64),
}


def objects(
    *,
    variant: str = "first",
    runtime_id: str = "codex_cli",
    observed_at: datetime = NOW - timedelta(minutes=10),
):
    manifest_sha, identity_sha, receipt_sha, envelope_sha = _DIGESTS[variant]
    manifest = SimpleNamespace(
        runtime_id=runtime_id,
        digest=manifest_sha,
        source_revision=REVISION,
    )
    identity = SimpleNamespace(digest=identity_sha)
    receipt = SimpleNamespace(
        digest=receipt_sha,
        finished_at=observed_at.isoformat(),
    )
    envelope = SimpleNamespace(
        runtime_id=runtime_id,
        runtime_manifest_sha256=manifest.digest,
        probe_identity_sha256=identity.digest,
        conformance_receipt_sha256=receipt.digest,
        source_revision=REVISION,
        digest=envelope_sha,
    )
    return envelope, identity, receipt, manifest


def admit(
    ledger: RuntimeTrustLedger,
    monkeypatch,
    *,
    variant: str = "first",
    admitted_at: datetime = NOW,
    observed_at: datetime | None = None,
    expires_at: datetime | None = None,
):
    calls = []

    def verified(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        verified,
    )
    observed = observed_at or admitted_at - timedelta(minutes=10)
    envelope, identity, receipt, manifest = objects(
        variant=variant,
        observed_at=observed,
    )
    record = ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(envelope.digest,),
        admitted_at=admitted_at,
        expires_at=expires_at or admitted_at + timedelta(hours=6),
    )
    assert calls and calls[0][1]["now"] == admitted_at
    return record, envelope, identity, receipt, manifest


def test_admission_persists_exact_live_binding_and_replays_idempotently(
    tmp_path, monkeypatch
) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    record, envelope, identity, receipt, manifest = admit(ledger, monkeypatch)

    active = ledger.require_active(
        runtime_id=manifest.runtime_id,
        envelope_sha256=envelope.digest,
        runtime_manifest_sha256=manifest.digest,
        conformance_receipt_sha256=receipt.digest,
        source_revision=manifest.source_revision,
        now=NOW + timedelta(minutes=1),
    )
    assert active == record
    assert record.probe_identity_sha256 == identity.digest
    assert record.observed_at == (NOW - timedelta(minutes=10)).isoformat(
        timespec="microseconds"
    )
    assert record.state == "ACTIVE"
    assert len(record.record_sha256) == 64

    replay = ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(envelope.digest,),
        admitted_at=NOW,
        expires_at=NOW + timedelta(hours=6),
    )
    assert replay == record
    assert ledger.records() == (record,)


def test_external_trust_failure_never_persists(monkeypatch, tmp_path) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")

    def refuse(*args, **kwargs):
        raise RuntimeConformanceError("not externally trusted")

    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        refuse,
    )
    envelope, identity, receipt, manifest = objects()
    with pytest.raises(RuntimeConformanceError, match="externally trusted"):
        ledger.admit(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=(),
            admitted_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    assert ledger.records() == ()


def test_rotation_quarantines_the_previous_runtime_identity(tmp_path, monkeypatch) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    first, first_envelope, _, first_receipt, first_manifest = admit(
        ledger, monkeypatch, variant="first"
    )
    second, second_envelope, _, second_receipt, second_manifest = admit(
        ledger,
        monkeypatch,
        variant="second",
        observed_at=NOW + timedelta(minutes=50),
        admitted_at=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(hours=7),
    )

    records = ledger.records("codex_cli")
    assert len(records) == 2
    old = next(item for item in records if item.envelope_sha256 == first.envelope_sha256)
    assert old.state == "QUARANTINED"
    assert old.reason == f"superseded-by:{second.envelope_sha256}"
    assert second.state == "ACTIVE"

    with pytest.raises(RuntimeTrustQuarantined, match="superseded"):
        ledger.require_active(
            runtime_id="codex_cli",
            envelope_sha256=first_envelope.digest,
            runtime_manifest_sha256=first_manifest.digest,
            conformance_receipt_sha256=first_receipt.digest,
            source_revision=REVISION,
            now=NOW + timedelta(hours=2),
        )
    assert ledger.require_active(
        runtime_id="codex_cli",
        envelope_sha256=second_envelope.digest,
        runtime_manifest_sha256=second_manifest.digest,
        conformance_receipt_sha256=second_receipt.digest,
        source_revision=REVISION,
        now=NOW + timedelta(hours=2),
    ) == second


def test_older_observation_cannot_roll_back_active_runtime(tmp_path, monkeypatch) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    current, _, _, _, _ = admit(
        ledger,
        monkeypatch,
        variant="first",
        observed_at=NOW - timedelta(minutes=1),
    )
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: None,
    )
    envelope, identity, receipt, manifest = objects(
        variant="stale",
        observed_at=NOW - timedelta(minutes=2),
    )
    with pytest.raises(RuntimeTrustBindingMismatch, match="not newer"):
        ledger.admit(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=(envelope.digest,),
            admitted_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
        )
    assert ledger.records() == (current,)


def test_expiry_is_persisted_as_monotonic_quarantine(tmp_path, monkeypatch) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    _, envelope, _, receipt, manifest = admit(
        ledger,
        monkeypatch,
        expires_at=NOW + timedelta(minutes=5),
    )
    with pytest.raises(RuntimeTrustExpired, match="expired"):
        ledger.require_active(
            runtime_id=manifest.runtime_id,
            envelope_sha256=envelope.digest,
            runtime_manifest_sha256=manifest.digest,
            conformance_receipt_sha256=receipt.digest,
            source_revision=REVISION,
            now=NOW + timedelta(minutes=5),
        )
    persisted = ledger.records()[0]
    assert persisted.state == "QUARANTINED"
    assert persisted.reason == "expired"
    with pytest.raises(RuntimeTrustQuarantined, match="expired"):
        ledger.require_active(
            runtime_id=manifest.runtime_id,
            envelope_sha256=envelope.digest,
            runtime_manifest_sha256=manifest.digest,
            conformance_receipt_sha256=receipt.digest,
            source_revision=REVISION,
            now=NOW + timedelta(minutes=6),
        )


def test_lookup_refuses_manifest_receipt_and_revision_repackaging(
    tmp_path, monkeypatch
) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    record, _, _, _, _ = admit(ledger, monkeypatch)
    for field, value in (
        ("runtime_manifest_sha256", "f" * 64),
        ("conformance_receipt_sha256", "e" * 64),
        ("source_revision", "2" * 40),
    ):
        values = {
            "runtime_id": record.runtime_id,
            "envelope_sha256": record.envelope_sha256,
            "runtime_manifest_sha256": record.runtime_manifest_sha256,
            "conformance_receipt_sha256": record.conformance_receipt_sha256,
            "source_revision": record.source_revision,
            "now": NOW + timedelta(minutes=1),
        }
        values[field] = value
        with pytest.raises(RuntimeTrustBindingMismatch, match=field):
            ledger.require_active(**values)
    assert ledger.records()[0].state == "ACTIVE"


def test_replay_cannot_extend_expiry_and_quarantine_cannot_be_rewritten(
    tmp_path, monkeypatch
) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    record, envelope, identity, receipt, manifest = admit(ledger, monkeypatch)
    with pytest.raises(RuntimeTrustBindingMismatch, match="changed persisted"):
        ledger.admit(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=(envelope.digest,),
            admitted_at=NOW,
            expires_at=NOW + timedelta(hours=7),
        )
    quarantined = ledger.quarantine(
        runtime_id=record.runtime_id,
        envelope_sha256=record.envelope_sha256,
        reason="binary-revoked",
        quarantined_at=NOW + timedelta(minutes=2),
    )
    assert quarantined.state == "QUARANTINED"
    assert ledger.quarantine(
        runtime_id=record.runtime_id,
        envelope_sha256=record.envelope_sha256,
        reason="binary-revoked",
        quarantined_at=NOW + timedelta(minutes=3),
    ) == quarantined
    with pytest.raises(RuntimeTrustQuarantined, match="another reason"):
        ledger.quarantine(
            runtime_id=record.runtime_id,
            envelope_sha256=record.envelope_sha256,
            reason="different-story",
            quarantined_at=NOW + timedelta(minutes=3),
        )


def test_database_tampering_is_detected_before_authorization(tmp_path, monkeypatch) -> None:
    path = tmp_path / "runtime-trust.sqlite3"
    ledger = RuntimeTrustLedger(path)
    record, _, _, _, _ = admit(ledger, monkeypatch)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE runtime_trust_records SET runtime_manifest_sha256=? "
            "WHERE envelope_sha256=?",
            ("f" * 64, record.envelope_sha256),
        )
    with pytest.raises(RuntimeTrustCorrupt, match="persisted"):
        ledger.records()


def test_receipt_freshness_and_naive_timestamps_fail_before_external_verification(
    tmp_path, monkeypatch
) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: pytest.fail("external verifier must not run"),
    )
    envelope, identity, receipt, manifest = objects(
        observed_at=NOW - timedelta(days=6)
    )
    with pytest.raises(ValueError, match="freshness window"):
        ledger.admit(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=(envelope.digest,),
            admitted_at=NOW,
            expires_at=NOW + timedelta(days=2),
        )
    envelope, identity, receipt, manifest = objects()
    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.admit(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=(envelope.digest,),
            admitted_at=datetime(2026, 8, 3, 1, 0),
            expires_at=NOW + timedelta(hours=1),
        )


def test_future_receipt_refuses_before_external_verification(tmp_path, monkeypatch) -> None:
    ledger = RuntimeTrustLedger(tmp_path / "runtime-trust.sqlite3")
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: pytest.fail("external verifier must not run"),
    )
    envelope, identity, receipt, manifest = objects(
        observed_at=NOW + timedelta(seconds=1)
    )
    with pytest.raises(RuntimeTrustBindingMismatch, match="after trust admission"):
        ledger.admit(
            envelope,
            identity,
            receipt,
            manifest,
            trusted_envelope_sha256s=(envelope.digest,),
            admitted_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
