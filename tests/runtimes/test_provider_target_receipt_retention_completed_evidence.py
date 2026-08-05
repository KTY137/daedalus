from __future__ import annotations

import dataclasses
import runpy
from pathlib import Path

import pytest

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


_LEDGER_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_provider_target_receipt_ledger.py"))
)
_fixture = _LEDGER_HELPERS["_fixture"]
_issue = _LEDGER_HELPERS["_issue"]
_ledger = _LEDGER_HELPERS["_ledger"]
_retain = _LEDGER_HELPERS["_retain"]
NOW = _LEDGER_HELPERS["NOW"]
TARGET_CONTRACT_ID = _LEDGER_HELPERS["TARGET_CONTRACT_ID"]
AUTHORITY_KEYRING = _LEDGER_HELPERS["AUTHORITY_KEYRING"]
OBSERVATION_KEYRING = _LEDGER_HELPERS["OBSERVATION_KEYRING"]
VERIFIER_KEYRING = _LEDGER_HELPERS["VERIFIER_KEYRING"]


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


def _verify(admission, recovery, ledger, receipt, fixture, **overrides):
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
        fixture.tree_ref,
        **values,
    )


def test_completed_retention_evidence_is_read_only_and_canonical(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
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

    assert evidence.retention_intent_id == retained.intent_id
    assert evidence.receipt_artifact_sha256 == receipt.digest
    assert evidence.provider_target_receipt_sha256 == receipt.digest
    assert evidence.start_receipt_sha256 == admission.start_receipt_sha256
    assert evidence.terminal_receipt_sha256 == admission.terminal_receipt_sha256
    assert evidence.to_dict()["retained_receipt_cas_verified"] is True
    assert evidence.to_dict()["persisted_effect_terminal_verified"] is False
    assert evidence.to_dict()["automatic_reexecution_allowed"] is False
    assert evidence.to_dict()["closed"] is False
    assert (
        ProviderTargetReceiptRetentionCompletedEvidenceReceipt.from_dict(
            evidence.to_dict()
        )
        == evidence
    )
    spine.close()


def test_completed_evidence_refuses_substituted_cas_bytes(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
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
        match="Event-Store or CAS evidence",
    ):
        _verify(admission, recovery, ledger, receipt, fixture)
    spine.close()


def test_completed_evidence_refuses_terminal_event_substitution(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
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


def test_completed_evidence_refuses_stale_and_non_completed_subjects(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    _retain(ledger, receipt, fixture)
    admission = _admission(primary, spine, ledger, fixture, receipt)
    recovery = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=receipt.source_revision,
    )

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
            expected_source_revision="f" * 40,
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
    fixture = _fixture(tmp_path / "fixture")
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
    spine.close()


def test_completed_evidence_wire_claims_fail_closed(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
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
        "retention_write_authorized",
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
    spine.close()
