from __future__ import annotations

import dataclasses
import os
import runpy
from pathlib import Path

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.runtimes.provider_target_receipt_ledger import (
    ProviderTargetReceiptLedger,
)
import daedalus.runtimes.provider_target_receipt_retention_completed_evidence as completed_module
from daedalus.runtimes.provider_target_receipt_retention_admission import (
    ProviderTargetReceiptRetentionAdmissionReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
    ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
    ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
    verify_provider_target_receipt_retention_completed_evidence,
)
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_GUARD_CONTRACT,
)
from daedalus.runtimes.provider_target_receipt_retention_recovery import (
    decide_provider_target_receipt_retention_recovery,
)
from daedalus.spine.envelope import canonical_json
from daedalus.spine.ledger import SpineLedger


_LEDGER_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_provider_target_receipt_ledger.py"))
)
_fixture = _LEDGER_HELPERS["_fixture"]
_issue = _LEDGER_HELPERS["_issue"]
_retain = _LEDGER_HELPERS["_retain"]
NOW = _LEDGER_HELPERS["NOW"]
TARGET_CONTRACT_ID = _LEDGER_HELPERS["TARGET_CONTRACT_ID"]
AUTHORITY_KEYRING = _LEDGER_HELPERS["AUTHORITY_KEYRING"]
OBSERVATION_KEYRING = _LEDGER_HELPERS["OBSERVATION_KEYRING"]
VERIFIER_KEYRING = _LEDGER_HELPERS["VERIFIER_KEYRING"]


def _ledger(tmp_path: Path, fixture):
    primary = tmp_path / "primary"
    primary.mkdir(parents=True)
    retention_root = tmp_path / "retention"
    spine = SpineLedger(retention_root / "state" / "spine.sqlite3")
    ledger = ProviderTargetReceiptLedger(
        spine,
        fixture.store,
        primary_checkout=primary,
    )
    return primary, spine, ledger


def _admission(primary, spine, ledger, fixture, receipt, **overrides):
    values = {
        "source_revision": receipt.source_revision,
        "preflight_sha256": "1" * 64,
        "provider_target_receipt_sha256": receipt.digest,
        "retention_inventory_sha256": "2" * 64,
        "retention_authority_sha256": "3" * 64,
        "retention_execution_request_sha256": fixture.execution.digest,
        "retention_effect_lease_sha256": "4" * 64,
        "retention_effect_lease_request_sha256": "5" * 64,
        "retention_policy_decision_sha256": "6" * 64,
        "guard_contract": RETENTION_GUARD_CONTRACT,
        "guard_evidence": (
            "authority_sha256=" + "7" * 64 + ";subject_sha256=" + "8" * 64
        ),
        "execution_state": "COMPLETED",
        "start_receipt_sha256": "9" * 64,
        "terminal_receipt_sha256": "a" * 64,
        "primary_checkout_path": str(primary.resolve()),
        "retention_root_path": str(spine.path.parent.parent.resolve()),
        "event_store_path": str(spine.path.resolve()),
        "receipt_cas_path": str(ledger.source_store.root.resolve()),
        "effect_lease_store_path": str(
            (spine.path.parent / "effect-leases.sqlite3").resolve()
        ),
    }
    values.update(overrides)
    return ProviderTargetReceiptRetentionAdmissionReceipt(**values)


def _verify(
    admission,
    recovery,
    ledger,
    receipt,
    fixture,
    *,
    source_tree_ref=None,
    **overrides,
):
    values = {
        "expected_source_revision": receipt.source_revision,
        "target_contract_id": TARGET_CONTRACT_ID,
        "authority_id": "authority.runtime-provider-observation",
        "authority_keyring": AUTHORITY_KEYRING,
        "observation_keyring": OBSERVATION_KEYRING,
        "verifier_id": "provider-target-verifier",
        "verifier_keyring": VERIFIER_KEYRING,
        "at": NOW,
    }
    values.update(overrides)
    return verify_provider_target_receipt_retention_completed_evidence(
        admission,
        recovery,
        ledger,
        receipt,
        fixture.target_authority,
        fixture.invocation_authority,
        fixture.identity_registry,
        fixture.execution,
        fixture.target_manifest,
        fixture.tree_ref if source_tree_ref is None else source_tree_ref,
        **values,
    )


def test_completed_retention_evidence_is_read_only_and_canonical(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    retained = _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )

    monkeypatch.setattr(
        spine,
        "record_intent",
        lambda *args, **kwargs: pytest.fail("read-only verifier wrote an intent"),
    )
    monkeypatch.setattr(
        fixture.store,
        "put_bytes",
        lambda *args, **kwargs: pytest.fail("read-only verifier wrote CAS bytes"),
    )

    evidence = _verify(admission, recovery, ledger, receipt, fixture)
    payload = evidence.to_dict()

    assert evidence.retention_intent_id == retained.intent_id
    assert evidence.receipt_artifact_sha256 == receipt.digest
    assert evidence.provider_target_receipt_sha256 == receipt.digest
    assert evidence.start_receipt_sha256 == admission.start_receipt_sha256
    assert evidence.terminal_receipt_sha256 == admission.terminal_receipt_sha256
    assert len(evidence.retention_topology_identity_sha256) == 64
    assert len(evidence.receipt_artifact_file_identity_sha256) == 64
    assert payload["retained_receipt_cas_verified"] is True
    assert payload["retention_topology_stable"] is True
    assert payload["receipt_artifact_identity_stable"] is True
    assert payload["persisted_effect_terminal_verified"] is False
    assert payload["automatic_reexecution_allowed"] is False
    assert payload["closed"] is False
    assert (
        ProviderTargetReceiptRetentionCompletedEvidenceReceipt.from_dict(payload)
        == evidence
    )
    spine.close()


def test_completed_evidence_refuses_substituted_cas_bytes(tmp_path) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    retained = _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )
    fixture.store._object_path(retained.artifact.sha256).write_bytes(b"substituted")

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="Event-Store or CAS evidence|provider-target receipt",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_hard_linked_artifact_identity(tmp_path) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    retained = _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )
    alias = tmp_path / "retained-receipt-alias"
    os.link(fixture.store._object_path(retained.artifact.sha256), alias)

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="one filesystem identity",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_terminal_event_substitution(tmp_path) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    retained = _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )
    replacement = canonical_json(
        {
            "effect_id": "0" * 64,
            "result": {
                "schema": "daedalus-provider-target-verification-retention-terminal/1",
                "receipt_sha256": receipt.digest,
                "receipt_artifact": retained.artifact.to_dict(),
            },
        }
    )
    with spine._txn() as connection:
        connection.execute(
            "UPDATE intent_events SET detail=? WHERE intent_id=? AND state='COMPLETED'",
            (replacement, retained.intent_id),
        )

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="Event-Store or CAS evidence",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def _topology_race_fixture(tmp_path):
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )
    return fixture, receipt, spine, ledger, admission, recovery


def test_completed_evidence_refuses_authentication_window_topology_race(
    tmp_path,
    monkeypatch,
) -> None:
    fixture, receipt, spine, ledger, admission, recovery = _topology_race_fixture(
        tmp_path
    )
    original = completed_module._topology_identity
    calls = 0

    def changing_topology(value):
        nonlocal calls
        calls += 1
        result = original(value)
        if calls == 2:
            result = {key: dict(identity) for key, identity in result.items()}
            result["event_store"]["inode"] += 1
        return result

    monkeypatch.setattr(completed_module, "_topology_identity", changing_topology)

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="receipt authentication",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_retained_read_window_topology_race(
    tmp_path,
    monkeypatch,
) -> None:
    fixture, receipt, spine, ledger, admission, recovery = _topology_race_fixture(
        tmp_path
    )
    original = completed_module._topology_identity
    calls = 0

    def changing_topology(value):
        nonlocal calls
        calls += 1
        result = original(value)
        if calls == 3:
            result = {key: dict(identity) for key, identity in result.items()}
            result["receipt_cas"]["inode"] += 1
        return result

    monkeypatch.setattr(completed_module, "_topology_identity", changing_topology)

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="completed-state verification",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_event_state_race(
    tmp_path,
    monkeypatch,
) -> None:
    fixture, receipt, spine, ledger, admission, recovery = _topology_race_fixture(
        tmp_path
    )
    original = completed_module._read_intent
    calls = 0

    def changing_intent(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2 and result is not None:
            return dataclasses.replace(result, trace_id="substituted-trace")
        return result

    monkeypatch.setattr(completed_module, "_read_intent", changing_intent)

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="state changed",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_stale_and_non_completed_subjects(tmp_path) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )
    stale = "0" * 40 if receipt.source_revision != "0" * 40 else "1" * 40

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="stale source revision",
    ):
        _verify(
            admission,
            recovery,
            ledger,
            receipt,
            fixture,
            expected_source_revision=stale,
        )

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
        match="exact 40-hex",
    ):
        _verify(
            admission,
            recovery,
            ledger,
            receipt,
            fixture,
            expected_source_revision="f" * 64,
        )

    failed_admission = dataclasses.replace(
        admission,
        execution_state="FAILED",
    )
    failed_recovery = decide_provider_target_receipt_retention_recovery(
        failed_admission,
        expected_source_revision=receipt.source_revision,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="admission is not completed",
    ):
        _verify(failed_admission, failed_recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_detached_and_non_exact_inputs(tmp_path) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )

    detached = dataclasses.replace(
        recovery,
        admission_sha256="0" * 64,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="detached from the retention admission",
    ):
        _verify(admission, detached, ledger, receipt, fixture)

    class DerivedAdmission(ProviderTargetReceiptRetentionAdmissionReceipt):
        pass

    derived = DerivedAdmission(
        **{
            field.name: getattr(admission, field.name)
            for field in dataclasses.fields(admission)
        }
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
        match="admission must be exact",
    ):
        _verify(derived, recovery, ledger, receipt, fixture)

    class DerivedArtifactRef(ArtifactRef):
        pass

    derived_ref = DerivedArtifactRef(
        sha256=fixture.tree_ref.sha256,
        locator=fixture.tree_ref.locator,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
        match="source_tree_ref must be exact",
    ):
        _verify(
            admission,
            recovery,
            ledger,
            receipt,
            fixture,
            source_tree_ref=derived_ref,
        )

    for invalid in (True, 0, -1):
        with pytest.raises(
            ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
            match="max_source_bytes",
        ):
            _verify(
                admission,
                recovery,
                ledger,
                receipt,
                fixture,
                max_source_bytes=invalid,
            )
    spine.close()


def test_completed_evidence_wire_claims_fail_closed(tmp_path) -> None:
    fixture = _fixture(tmp_path / "retention" / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )
    evidence = _verify(admission, recovery, ledger, receipt, fixture)

    for field in (
        "persisted_effect_terminal_verified",
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        payload = evidence.to_dict()
        payload[field] = True
        with pytest.raises(
            ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
            match="unsupported claim",
        ):
            ProviderTargetReceiptRetentionCompletedEvidenceReceipt.from_dict(payload)

    for field in (
        "retention_topology_stable",
        "receipt_artifact_identity_stable",
    ):
        payload = evidence.to_dict()
        payload[field] = False
        with pytest.raises(
            ProviderTargetReceiptRetentionCompletedEvidenceShapeError,
            match="lost required claim",
        ):
            ProviderTargetReceiptRetentionCompletedEvidenceReceipt.from_dict(payload)
    spine.close()
