# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.artifacts import digest_file_tree
from daedalus.kernel.attempts import (
    AttemptLedger,
    AttemptWorkspaceError,
    IsolatedAttemptCoordinator,
)
from daedalus.schemas import AttemptContract, ContractProvenance, ResourceBudget


REVISION = "a" * 40
FIXTURE_TIME = "2026-08-03T22:00:00+00:00"
TASK_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
POLICY_SHA = "3" * 64


def _value(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def _primary(tmp_path: Path) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "work.py").write_text("value = 1\n", encoding="utf-8")
    return primary


def _attempt(attempt_id: str = "attempt-time") -> AttemptContract:
    return AttemptContract(
        attempt_id=attempt_id,
        mission_id="mission-time",
        task_id="task-time",
        instruction="Operate only in the isolated workspace.",
        base_revision=REVISION,
        task_sha256=TASK_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        policy_decision_sha256=POLICY_SHA,
        budget=ResourceBudget(max_wall_time_s=30),
        provenance=ContractProvenance(
            origin="tests.attempt-time",
            source_revision=REVISION,
            created_at=FIXTURE_TIME,
            input_digests=(POLICY_SHA, RUNTIME_SHA, TASK_SHA),
        ),
        writable_paths=("work.py",),
        gate_names=("pytest",),
    )


def _environment(tmp_path: Path):
    primary = _primary(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    captured = store.capture_tree(
        primary,
        tree_id="input-time",
        source_revision=REVISION,
        origin="tests.attempt-time-input",
        created_at=FIXTURE_TIME,
    )
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    coordinator = IsolatedAttemptCoordinator(
        primary_checkout=primary,
        workspace_parent=tmp_path / "workspaces",
        source_store=store,
        ledger=ledger,
    )
    return primary, store, captured, ledger, coordinator


def test_caller_start_and_completion_times_have_no_security_authority(tmp_path) -> None:
    _primary_root, store, captured, ledger, coordinator = _environment(tmp_path)
    hostile_future = "2099-01-01T00:00:00+00:00"
    hostile_past = "1970-01-01T00:00:00+00:00"

    prepared = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-time",
        started_at=hostile_future,
    )
    assert prepared.begin.start.started_at != hostile_future
    assert prepared.begin.start.provenance.created_at == prepared.begin.start.started_at

    report = store.put_bytes(b"trusted terminal report")
    completion = ledger.complete(
        prepared.begin.start,
        receipt_id="terminal-time",
        outcome="failed",
        report=report,
        candidate_tree=None,
        completed_at=hostile_past,
    )
    assert completion.receipt.completed_at != hostile_past
    assert completion.receipt.provenance.created_at == completion.receipt.completed_at
    assert _value(completion.receipt.completed_at) > _value(
        prepared.begin.start.started_at
    )


def test_lifecycle_clock_is_monotonic_across_distinct_attempts(tmp_path) -> None:
    _primary_root, _store, captured, ledger, coordinator = _environment(tmp_path)
    first = coordinator.prepare(
        _attempt("attempt-time-1"),
        captured,
        start_id="start-time-1",
    )
    second = coordinator.prepare(
        _attempt("attempt-time-2"),
        captured,
        start_id="start-time-2",
    )
    assert _value(second.begin.start.started_at) > _value(first.begin.start.started_at)
    assert ledger.pending() == (first.begin.start, second.begin.start)


def test_refused_primary_nested_workspace_is_not_created(tmp_path) -> None:
    primary = _primary(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    candidate = primary / "new-workspaces"
    before = digest_file_tree(primary)

    with pytest.raises(AttemptWorkspaceError, match="primary checkout"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=candidate,
            source_store=store,
            ledger=ledger,
        )

    assert not candidate.exists()
    assert digest_file_tree(primary) == before


def test_refused_cas_nested_workspace_is_not_created(tmp_path) -> None:
    primary = _primary(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    candidate = store.root / "new-workspaces"

    with pytest.raises(AttemptWorkspaceError, match="source-tree store"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=candidate,
            source_store=store,
            ledger=ledger,
        )

    assert not candidate.exists()


def test_parent_symlink_redirect_into_primary_is_refused_before_child_creation(
    tmp_path,
) -> None:
    primary = _primary(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    redirect = tmp_path / "redirect"
    try:
        redirect.symlink_to(primary, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    candidate = redirect / "child"
    before = digest_file_tree(primary)

    with pytest.raises(AttemptWorkspaceError, match="primary checkout"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=candidate,
            source_store=store,
            ledger=ledger,
        )

    assert not (primary / "child").exists()
    assert digest_file_tree(primary) == before


def test_broken_workspace_leaf_symlink_is_refused(tmp_path) -> None:
    primary = _primary(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    candidate = tmp_path / "broken-workspaces"
    try:
        candidate.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")

    with pytest.raises(AttemptWorkspaceError, match="must not be a symlink"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=candidate,
            source_store=store,
            ledger=ledger,
        )
    assert candidate.is_symlink()
