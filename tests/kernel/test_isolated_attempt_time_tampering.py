from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempts import (
    AttemptLedger,
    AttemptStateError,
    AttemptTerminalReceipt,
    IsolatedAttemptCoordinator,
)
from daedalus.schemas import AttemptContract, ContractProvenance, ResourceBudget
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
FIXTURE_TIME = "2026-08-03T22:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
TASK_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
POLICY_SHA = "3" * 64


def _environment(tmp_path: Path):
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "work.py").write_text("value = 1\n", encoding="utf-8")
    store = SourceTreeStore(tmp_path / "cas")
    captured = store.capture_tree(
        primary,
        tree_id="input-time-tamper",
        source_revision=REVISION,
        origin="tests.attempt-time-tamper-input",
        created_at=FIXTURE_TIME,
    )
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    coordinator = IsolatedAttemptCoordinator(
        primary_checkout=primary,
        workspace_parent=tmp_path / "workspaces",
        source_store=store,
        ledger=ledger,
    )
    attempt = AttemptContract(
        attempt_id="attempt-time-tamper",
        mission_id="mission-time-tamper",
        task_id="task-time-tamper",
        instruction="Operate only in the isolated workspace.",
        base_revision=REVISION,
        task_sha256=TASK_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        policy_decision_sha256=POLICY_SHA,
        budget=ResourceBudget(max_wall_time_s=30),
        provenance=ContractProvenance(
            origin="tests.attempt-time-tamper",
            source_revision=REVISION,
            created_at=FIXTURE_TIME,
            input_digests=(POLICY_SHA, RUNTIME_SHA, TASK_SHA),
        ),
        writable_paths=("work.py",),
        gate_names=("pytest",),
    )
    return store, captured, ledger, coordinator, attempt


def test_repacked_future_start_time_is_refused_against_event_store_time(tmp_path) -> None:
    _store, captured, ledger, coordinator, attempt = _environment(tmp_path)
    coordinator.prepare(attempt, captured, start_id="start-time-tamper")

    with sqlite3.connect(ledger.path) as connection:
        row = connection.execute(
            "SELECT id, payload FROM intents WHERE kind = 'attempt.lifecycle'"
        ).fetchone()
        payload = json.loads(row[1])
        payload["start"]["started_at"] = FUTURE
        payload["start"]["provenance"]["created_at"] = FUTURE
        raw = canonical_json(payload)
        digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
        connection.execute(
            "UPDATE intents SET payload = ?, payload_sha = ? WHERE id = ?",
            (raw, digest, row[0]),
        )
        connection.execute(
            "UPDATE intent_events SET detail = ? "
            "WHERE intent_id = ? AND state = 'INTENDED'",
            (canonical_json({"payload_sha": digest}), row[0]),
        )

    with pytest.raises(AttemptStateError, match="follows its Event-Store start"):
        ledger.pending()


def test_repacked_future_terminal_time_is_refused_against_event_store_time(tmp_path) -> None:
    store, captured, ledger, coordinator, attempt = _environment(tmp_path)
    prepared = coordinator.prepare(attempt, captured, start_id="start-time-tamper")
    report = store.put_bytes(b"terminal")
    ledger.complete(
        prepared.begin.start,
        receipt_id="terminal-time-tamper",
        outcome="failed",
        report=report,
        candidate_tree=None,
    )

    with sqlite3.connect(ledger.path) as connection:
        row = connection.execute(
            "SELECT id, detail FROM intent_events "
            "WHERE state = 'COMPLETED' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        detail = json.loads(row[1])
        receipt_payload = detail["result"]["receipt"]
        receipt_payload["completed_at"] = FUTURE
        receipt_payload["provenance"]["created_at"] = FUTURE
        receipt = AttemptTerminalReceipt.from_dict(receipt_payload)
        detail["effect_id"] = receipt.digest
        connection.execute(
            "UPDATE intent_events SET detail = ? WHERE id = ?",
            (canonical_json(detail), row[0]),
        )

    with pytest.raises(AttemptStateError, match="follows its Event-Store terminal"):
        coordinator.prepare(attempt, captured, start_id="start-time-tamper")
