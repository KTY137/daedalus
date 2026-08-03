from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

import daedalus.kernel.attempt_ledger as attempt_ledger_impl
import daedalus.kernel.attempt_workspace as attempt_workspace_impl
import daedalus.spine.ledger as spine_ledger_impl
from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempts import AttemptLedger, AttemptStateError
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    ResourceBudget,
)
from daedalus.spine.envelope import canonical_json

REVISION = "a" * 40
TASK_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
POLICY_SHA = "3" * 64
START = "2026-08-03T22:00:00+00:00"
START_EVENT = "2026-08-03T22:00:00.100000+00:00"
COMPLETE = "2026-08-03T22:01:00+00:00"
COMPLETE_EVENT = "2026-08-03T22:01:00.100000+00:00"


def _attempt() -> AttemptContract:
    return AttemptContract(
        attempt_id="attempt-time",
        mission_id="mission-time",
        task_id="task-time",
        instruction="Exercise only the lifecycle time authority.",
        base_revision=REVISION,
        task_sha256=TASK_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        policy_decision_sha256=POLICY_SHA,
        budget=ResourceBudget(max_wall_time_s=30),
        provenance=ContractProvenance(
            origin="tests.attempt-authority-time",
            source_revision=REVISION,
            created_at=START,
            input_digests=(POLICY_SHA, RUNTIME_SHA, TASK_SHA),
        ),
        writable_paths=("value.py",),
        gate_names=("pytest",),
    )


def _environment(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "value.py").write_text("value = 1\n", encoding="utf-8")
    store = SourceTreeStore(tmp_path / "cas")
    captured = store.capture_tree(
        source,
        tree_id="input-time",
        source_revision=REVISION,
        origin="tests.attempt-authority-time-input",
        created_at=START,
    )
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    return store, captured, ledger


def _begin(ledger: AttemptLedger, captured):
    return ledger.begin(
        _attempt(),
        captured,
        start_id="start-time",
        workspace_parent_sha256="4" * 64,
        workspace_relative_path="attempts/attempt-time-fixed",
    )


def _set_clocks(monkeypatch, *, authority: str, spine: str) -> None:
    monkeypatch.setattr(attempt_ledger_impl, "_authority_now", lambda: authority)
    monkeypatch.setattr(spine_ledger_impl, "_now_iso", lambda: spine)


def test_public_lifecycle_mutation_api_cannot_accept_caller_timestamps() -> None:
    assert "started_at" not in inspect.signature(AttemptLedger.begin).parameters
    assert "completed_at" not in inspect.signature(AttemptLedger.complete).parameters
    assert "started_at" not in inspect.signature(
        attempt_workspace_impl.IsolatedAttemptCoordinator.prepare
    ).parameters


def test_start_uses_authority_time_and_binds_nearby_event_store_time(
    tmp_path, monkeypatch
) -> None:
    _store, captured, ledger = _environment(tmp_path)
    _set_clocks(monkeypatch, authority=START, spine=START_EVENT)
    begin = _begin(ledger, captured)
    assert begin.start.started_at == START
    assert begin.start.provenance.created_at == START
    assert ledger.pending() == (begin.start,)


def test_future_or_stale_authority_time_fails_closed_against_event_store(
    tmp_path, monkeypatch
) -> None:
    _store, captured, ledger = _environment(tmp_path)
    _set_clocks(
        monkeypatch,
        authority="2026-08-03T23:00:00+00:00",
        spine=START_EVENT,
    )
    with pytest.raises(AttemptStateError, match="precedes authority"):
        _begin(ledger, captured)


def test_event_row_time_substitution_is_rejected_before_hydration(
    tmp_path, monkeypatch
) -> None:
    _store, captured, ledger = _environment(tmp_path)
    _set_clocks(monkeypatch, authority=START, spine=START_EVENT)
    _begin(ledger, captured)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE intents SET created_ts=? WHERE kind='attempt.lifecycle'",
            ("2026-08-03T19:00:00+00:00",),
        )
    with pytest.raises(AttemptStateError, match="event time does not bind"):
        ledger.pending()


def test_persisted_record_time_repackaging_outside_bound_is_rejected(
    tmp_path, monkeypatch
) -> None:
    _store, captured, ledger = _environment(tmp_path)
    _set_clocks(monkeypatch, authority=START, spine=START_EVENT)
    _begin(ledger, captured)
    with sqlite3.connect(ledger.path) as connection:
        row = connection.execute(
            "SELECT id, payload FROM intents WHERE kind='attempt.lifecycle'"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[1])
        payload["start"]["started_at"] = "2026-08-03T20:00:00+00:00"
        payload["start"]["provenance"]["created_at"] = (
            "2026-08-03T20:00:00+00:00"
        )
        wire = canonical_json(payload)
        digest = hashlib.sha256(wire.encode("ascii")).hexdigest()
        connection.execute(
            "UPDATE intents SET payload=?, payload_sha=? WHERE id=?",
            (wire, digest, row[0]),
        )
        connection.execute(
            "UPDATE intent_events SET detail=? "
            "WHERE intent_id=? AND state='INTENDED'",
            (canonical_json({"payload_sha": digest}), row[0]),
        )
    with pytest.raises(AttemptStateError, match="not bound"):
        ledger.pending()


def test_completion_cannot_precede_authority_owned_start(tmp_path, monkeypatch) -> None:
    store, captured, ledger = _environment(tmp_path)
    _set_clocks(monkeypatch, authority=START, spine=START_EVENT)
    start = _begin(ledger, captured).start
    monkeypatch.setattr(
        attempt_ledger_impl,
        "_authority_now",
        lambda: "2026-08-03T21:59:00+00:00",
    )
    with pytest.raises(AttemptStateError, match="cannot precede start"):
        ledger.complete(
            start,
            receipt_id="terminal-time",
            outcome="failed",
            report=store.put_bytes(b"failed"),
            candidate_tree=None,
        )
    assert ledger.pending() == (start,)


def test_terminal_record_time_repackaging_before_start_is_rejected(
    tmp_path, monkeypatch
) -> None:
    store, captured, ledger = _environment(tmp_path)
    _set_clocks(monkeypatch, authority=START, spine=START_EVENT)
    start = _begin(ledger, captured).start
    monkeypatch.setattr(attempt_ledger_impl, "_authority_now", lambda: COMPLETE)
    monkeypatch.setattr(spine_ledger_impl, "_now_iso", lambda: COMPLETE_EVENT)
    completion = ledger.complete(
        start,
        receipt_id="terminal-time",
        outcome="failed",
        report=store.put_bytes(b"failed"),
        candidate_tree=None,
    )

    repacked_time = "2026-08-03T21:00:00+00:00"
    repacked_receipt = dataclasses.replace(
        completion.receipt,
        completed_at=repacked_time,
        provenance=dataclasses.replace(
            completion.receipt.provenance,
            created_at=repacked_time,
        ),
    )
    with sqlite3.connect(ledger.path) as connection:
        row = connection.execute(
            "SELECT id, detail FROM intent_events "
            "WHERE state='COMPLETED' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        detail = json.loads(row[1])
        detail["result"]["receipt"] = repacked_receipt.to_dict()
        detail["effect_id"] = repacked_receipt.digest
        connection.execute(
            "UPDATE intent_events SET detail=? WHERE id=?",
            (canonical_json(detail), row[0]),
        )

    with pytest.raises(AttemptStateError, match="precedes persisted start"):
        _begin(ledger, captured)
    assert completion.receipt.completed_at == COMPLETE
