from __future__ import annotations

import dataclasses
import os
import runpy
from pathlib import Path

import pytest

import daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence as terminal_module
from daedalus.kernel.effect_replay import EffectExecutionReplaySnapshot
from daedalus.kernel.effects import EffectTerminalReceipt, LeasedEffectStartReceipt
from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence import (
    ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
    ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt,
    ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError,
    verify_provider_target_receipt_retention_effect_terminal_evidence,
)


_ADMISSION_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_provider_target_receipt_retention_admission.py"))
)
_subjects = _ADMISSION_HELPERS["_subjects"]
REVISION = _ADMISSION_HELPERS["REVISION"]


def _completed(subjects, **overrides):
    values = {
        "source_revision": REVISION,
        "admission_sha256": "1" * 64,
        "recovery_decision_sha256": "2" * 64,
        "provider_target_receipt_sha256": "3" * 64,
        "target_projection_sha256": "4" * 64,
        "receipt_artifact_sha256": "3" * 64,
        "retention_intent_id": 7,
        "retention_intent_payload_sha256": "5" * 64,
        "retention_event_evidence_sha256": "6" * 64,
        "retention_topology_identity_sha256": "7" * 64,
        "receipt_artifact_file_identity_sha256": "8" * 64,
        "start_receipt_sha256": "9" * 64,
        "terminal_receipt_sha256": "a" * 64,
        "event_store_path": str(subjects.event.resolve()),
        "receipt_cas_path": str(subjects.cas.resolve()),
    }
    values.update(overrides)
    return ProviderTargetReceiptRetentionCompletedEvidenceReceipt(**values)


def _snapshot(subjects, completed, **terminal_overrides):
    start = LeasedEffectStartReceipt(
        lease_sha256=subjects.authorization.lease.digest,
        execution_id=subjects.execution.execution_id,
        idempotency_key=subjects.execution.idempotency_key,
        execution_request_sha256=subjects.execution.digest,
        boundary_receipt_sha256="b" * 64,
        started_at="2026-08-05T08:00:00.000000+00:00",
        receipt_sha256=completed.start_receipt_sha256,
    )
    values = {
        "lease_sha256": subjects.authorization.lease.digest,
        "execution_id": subjects.execution.execution_id,
        "start_receipt_sha256": start.receipt_sha256,
        "outcome": "COMPLETED",
        "output_digests": (completed.receipt_artifact_sha256,),
        "detail_sha256": None,
        "finished_at": "2026-08-05T08:01:00.000000+00:00",
        "receipt_sha256": completed.terminal_receipt_sha256,
    }
    values.update(terminal_overrides)
    terminal = EffectTerminalReceipt(**values)
    return EffectExecutionReplaySnapshot(start, "COMPLETED", terminal)


def _verify(subjects, completed):
    return verify_provider_target_receipt_retention_effect_terminal_evidence(
        completed,
        subjects.authorization,
        subjects.execution,
        expected_source_revision=REVISION,
    )


def test_effect_terminal_evidence_is_read_only_canonical_and_double_read(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(subjects, completed)
    calls = 0

    def inspect(*args, **kwargs):
        nonlocal calls
        calls += 1
        return snapshot

    monkeypatch.setattr(terminal_module, "inspect_effect_execution", inspect)
    evidence = _verify(subjects, completed)
    payload = evidence.to_dict()

    assert calls == 2
    assert evidence.completed_evidence_sha256 == completed.digest
    assert evidence.retention_execution_request_sha256 == subjects.execution.digest
    assert evidence.retention_effect_lease_sha256 == subjects.authorization.lease.digest
    assert evidence.start_receipt_sha256 == completed.start_receipt_sha256
    assert evidence.terminal_receipt_sha256 == completed.terminal_receipt_sha256
    assert payload["persisted_effect_terminal_verified"] is True
    assert payload["retained_receipt_output_bound"] is True
    assert payload["automatic_reexecution_allowed"] is False
    assert payload["owner_approval_issued"] is False
    assert payload["promotion_authorized"] is False
    assert payload["closed"] is False
    assert (
        ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt.from_dict(payload)
        == evidence
    )


def test_effect_terminal_evidence_refuses_stale_or_generic_revision(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: _snapshot(subjects, completed),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError,
        match="40-hex",
    ):
        verify_provider_target_receipt_retention_effect_terminal_evidence(
            completed,
            subjects.authorization,
            subjects.execution,
            expected_source_revision="f" * 64,
        )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="stale source revision",
    ):
        verify_provider_target_receipt_retention_effect_terminal_evidence(
            completed,
            subjects.authorization,
            subjects.execution,
            expected_source_revision="e" * 40,
        )


def test_effect_terminal_evidence_refuses_absent_started_or_failed_state(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)

    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: None,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="absent or non-exact",
    ):
        _verify(subjects, completed)

    started = _snapshot(subjects, completed)
    started = EffectExecutionReplaySnapshot(started.start_receipt, "STARTED", None)
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: started,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="not COMPLETED",
    ):
        _verify(subjects, completed)

    failed_terminal = dataclasses.replace(
        _snapshot(subjects, completed).terminal_receipt,
        outcome="FAILED",
    )
    failed = EffectExecutionReplaySnapshot(
        _snapshot(subjects, completed).start_receipt,
        "FAILED",
        failed_terminal,
    )
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: failed,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="not COMPLETED",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_receipt_and_output_substitution(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)

    wrong_start = _snapshot(subjects, completed)
    wrong_start = EffectExecutionReplaySnapshot(
        dataclasses.replace(wrong_start.start_receipt, receipt_sha256="c" * 64),
        "COMPLETED",
        wrong_start.terminal_receipt,
    )
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: wrong_start,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="start receipt is detached",
    ):
        _verify(subjects, completed)

    wrong_terminal = _snapshot(
        subjects,
        completed,
        receipt_sha256="d" * 64,
    )
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: wrong_terminal,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="terminal receipt is detached",
    ):
        _verify(subjects, completed)

    wrong_output = _snapshot(
        subjects,
        completed,
        output_digests=("e" * 64,),
    )
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: wrong_output,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="terminal output is detached",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_two_read_state_race(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    first = _snapshot(subjects, completed)
    second = _snapshot(
        subjects,
        completed,
        finished_at="2026-08-05T08:02:00.000000+00:00",
    )
    values = iter((first, second))
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: next(values),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="changed between read-only projections",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_store_identity_race(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(subjects, completed)
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: snapshot,
    )
    original = terminal_module._effect_store_identity
    calls = 0

    def changing(path):
        nonlocal calls
        calls += 1
        result = original(path)
        if calls == 2:
            return {**result, "inode": result["inode"] + 1}
        return result

    monkeypatch.setattr(terminal_module, "_effect_store_identity", changing)
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="changed during the first replay projection",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_hard_linked_effect_store(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: _snapshot(subjects, completed),
    )
    os.link(subjects.effect_store, tmp_path / "effect-store-alias.sqlite3")

    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="one filesystem identity",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_subclasses_and_claim_escalation(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: _snapshot(subjects, completed),
    )

    class CompletedSubclass(
        ProviderTargetReceiptRetentionCompletedEvidenceReceipt
    ):
        pass

    subclassed = CompletedSubclass(
        **{
            field.name: getattr(completed, field.name)
            for field in dataclasses.fields(completed)
        }
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError,
        match="must be exact",
    ):
        verify_provider_target_receipt_retention_effect_terminal_evidence(
            subclassed,
            subjects.authorization,
            subjects.execution,
            expected_source_revision=REVISION,
        )

    evidence = _verify(subjects, completed)
    payload = evidence.to_dict()
    payload["closed"] = True
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError,
        match="unsupported claim",
    ):
        ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt.from_dict(payload)
