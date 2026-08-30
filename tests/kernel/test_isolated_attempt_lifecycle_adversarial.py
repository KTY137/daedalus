# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempts import (
    AttemptLedger,
    AttemptStateError,
    AttemptWorkspaceError,
    IsolatedAttemptCoordinator,
)
from daedalus.kernel.source_trees import SourceTreeStoreError
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    ResourceBudget,
)
from daedalus.spine.ledger import SpineLedger


REVISION = "a" * 40
NOW = "2026-08-03T22:00:00+00:00"
TASK_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
POLICY_SHA = "3" * 64


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.py").write_text("value = 1\n", encoding="utf-8")
    return source


def _attempt() -> AttemptContract:
    return AttemptContract(
        attempt_id="attempt-adversarial",
        mission_id="mission-1",
        task_id="task-1",
        instruction="Operate only in an isolated workspace.",
        base_revision=REVISION,
        task_sha256=TASK_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        policy_decision_sha256=POLICY_SHA,
        budget=ResourceBudget(max_wall_time_s=30),
        provenance=ContractProvenance(
            origin="tests.attempt-adversarial",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(POLICY_SHA, RUNTIME_SHA, TASK_SHA),
        ),
        writable_paths=("work.py",),
        gate_names=("pytest",),
    )


def _captured(
    store: SourceTreeStore,
    source: Path,
    *,
    tree_id: str = "input-tree-adversarial",
):
    return store.capture_tree(
        source,
        tree_id=tree_id,
        source_revision=REVISION,
        origin="tests.attempt-adversarial-input",
        created_at=NOW,
    )


def _begin(ledger: AttemptLedger, captured, parent_digest: str = "4" * 64):
    return ledger.begin(
        _attempt(),
        captured,
        start_id="start-attempt-adversarial",
        workspace_parent_sha256=parent_digest,
        workspace_relative_path="attempts/attempt-adversarial-fixed",
        started_at=NOW,
    )


def test_ledger_requires_one_canonical_source_store(tmp_path) -> None:
    with pytest.raises(AttemptStateError, match="SourceTreeStore"):
        AttemptLedger(tmp_path / "attempts.sqlite3", object())


def test_attempt_facade_uses_the_supplied_canonical_spine_instance(tmp_path) -> None:
    store = SourceTreeStore(tmp_path / "cas")
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")
    ledger = AttemptLedger(spine, store)
    assert ledger.spine is spine
    assert ledger.path == spine.path
    with sqlite3.connect(ledger.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "intents" in tables
    assert "intent_events" in tables
    assert "attempt_starts" not in tables
    assert "attempt_terminals" not in tables


def test_foreign_store_input_is_refused_before_start(tmp_path) -> None:
    source = _source(tmp_path)
    foreign_store = SourceTreeStore(tmp_path / "foreign-cas")
    captured = _captured(foreign_store, source)
    selected_store = SourceTreeStore(tmp_path / "selected-cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", selected_store)

    with pytest.raises(SourceTreeStoreError, match="unavailable|CAS object"):
        _begin(ledger, captured)
    assert ledger.pending() == ()


def test_coordinator_rejects_equal_but_distinct_store_authority(tmp_path) -> None:
    primary = _source(tmp_path)
    selected_store = SourceTreeStore(tmp_path / "cas")
    alias_store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", selected_store)
    with pytest.raises(AttemptWorkspaceError, match="exact SourceTreeStore"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=tmp_path / "workspaces",
            source_store=alias_store,
            ledger=ledger,
        )


def test_terminal_rejects_report_not_present_in_selected_store(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "selected-cas")
    captured = _captured(store, source)
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    start = _begin(ledger, captured).start
    foreign_store = SourceTreeStore(tmp_path / "foreign-cas")
    foreign_report = foreign_store.put_bytes(b"foreign report")

    with pytest.raises(SourceTreeStoreError, match="unavailable|CAS object"):
        ledger.complete(
            start,
            receipt_id="terminal-attempt-adversarial",
            outcome="failed",
            report=foreign_report,
            candidate_tree=None,
            completed_at=NOW,
        )
    assert len(ledger.pending()) == 1


def test_terminal_rejects_candidate_not_present_in_selected_store(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "selected-cas")
    captured = _captured(store, source)
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    start = _begin(ledger, captured).start
    report = store.put_bytes(b"failed")

    foreign_source = tmp_path / "foreign-source"
    foreign_source.mkdir()
    (foreign_source / "work.py").write_text("value = 2\n", encoding="utf-8")
    foreign_store = SourceTreeStore(tmp_path / "foreign-cas")
    foreign_candidate = _captured(
        foreign_store,
        foreign_source,
        tree_id="foreign-candidate",
    )

    with pytest.raises(SourceTreeStoreError, match="unavailable|CAS object"):
        ledger.complete(
            start,
            receipt_id="terminal-attempt-adversarial",
            outcome="failed",
            report=report,
            candidate_tree=foreign_candidate,
            completed_at=NOW,
        )


def test_persisted_start_wire_tampering_fails_closed(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    captured = _captured(store, source)
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    _begin(ledger, captured)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE intents SET payload = ? WHERE kind = 'attempt.lifecycle'",
            (
                '{"schema":"daedalus-attempt-lifecycle-event/1",'
                '"schema":"duplicate"}',
            ),
        )
    with pytest.raises(AttemptStateError, match="duplicate key|malformed"):
        _begin(ledger, captured)


def test_terminal_effect_id_tampering_fails_closed(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    captured = _captured(store, source)
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    start = _begin(ledger, captured).start
    report = store.put_bytes(b"terminal report")
    ledger.complete(
        start,
        receipt_id="terminal-attempt-adversarial",
        outcome="failed",
        report=report,
        candidate_tree=None,
        completed_at=NOW,
    )
    with sqlite3.connect(ledger.path) as connection:
        row = connection.execute(
            "SELECT id, detail FROM intent_events "
            "WHERE state = 'COMPLETED' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        detail = json.loads(row[1])
        detail["effect_id"] = "f" * 64
        connection.execute(
            "UPDATE intent_events SET detail = ? WHERE id = ?",
            (json.dumps(detail, sort_keys=True, separators=(",", ":")), row[0]),
        )
    with pytest.raises(AttemptStateError, match="effect_id"):
        _begin(ledger, captured)


def test_persisted_terminal_artifact_is_reverified_on_replay(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    captured = _captured(store, source)
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    start = _begin(ledger, captured).start
    report = store.put_bytes(b"terminal report")
    ledger.complete(
        start,
        receipt_id="terminal-attempt-adversarial",
        outcome="failed",
        report=report,
        candidate_tree=None,
        completed_at=NOW,
    )
    store._object_path(report.sha256).write_bytes(b"corrupt")

    with pytest.raises(SourceTreeStoreError, match="address|invalid|bound"):
        _begin(ledger, captured)


def test_constructor_shaped_attempt_and_tree_are_refused(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    captured = _captured(store, source)
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    fake_attempt = SimpleNamespace(
        attempt_id="attempt-adversarial",
        base_revision=REVISION,
        digest="5" * 64,
    )
    with pytest.raises(Exception, match="AttemptContract"):
        ledger.begin(
            fake_attempt,
            captured,
            start_id="start-attempt-adversarial",
            workspace_parent_sha256="4" * 64,
            workspace_relative_path="attempts/fake",
            started_at=NOW,
        )
    fake_tree = SimpleNamespace(manifest=captured.manifest, ref=captured.ref)
    with pytest.raises(Exception, match="StoredSourceTree"):
        ledger.begin(
            _attempt(),
            fake_tree,
            start_id="start-attempt-adversarial",
            workspace_parent_sha256="4" * 64,
            workspace_relative_path="attempts/fake",
            started_at=NOW,
        )
