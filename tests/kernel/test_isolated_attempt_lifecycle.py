from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.artifacts import digest_file_tree
from daedalus.kernel.attempts import (
    AttemptBindingMismatch,
    AttemptLedger,
    AttemptReplay,
    AttemptWorkspaceError,
    IsolatedAttemptCoordinator,
)
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    ResourceBudget,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
NOW = "2026-08-03T21:30:00+00:00"
LATER = "2026-08-03T21:31:00+00:00"
TASK_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
POLICY_SHA = "3" * 64


def _primary(tmp_path: Path) -> Path:
    root = tmp_path / "primary"
    (root / "src").mkdir(parents=True)
    (root / "src" / "event.py").write_text(
        "class Event:\n    voltage = 5\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Candidate\n", encoding="utf-8")
    return root


def _attempt(*, attempt_id: str = "attempt-1", revision: str = REVISION) -> AttemptContract:
    return AttemptContract(
        attempt_id=attempt_id,
        mission_id="mission-1",
        task_id="task-1",
        instruction="Rename one bounded symbol in the isolated workspace.",
        base_revision=revision,
        task_sha256=TASK_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        policy_decision_sha256=POLICY_SHA,
        budget=ResourceBudget(max_wall_time_s=60, max_attempts=2),
        provenance=ContractProvenance(
            origin="tests.isolated-attempt",
            source_revision=revision,
            created_at=NOW,
            input_digests=(POLICY_SHA, RUNTIME_SHA, TASK_SHA),
            trace_id="mission-1",
        ),
        writable_paths=("src/event.py", "README.md"),
        gate_names=("pytest", "schema"),
    )


def _environment(tmp_path: Path):
    primary = _primary(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    captured = store.capture_tree(
        primary,
        tree_id="input-tree-1",
        source_revision=REVISION,
        origin="tests.isolated-attempt-input",
        created_at=NOW,
        trace_id="attempt-1",
    )
    ledger = AttemptLedger(tmp_path / "state" / "attempts.sqlite3")
    coordinator = IsolatedAttemptCoordinator(
        primary_checkout=primary,
        workspace_parent=tmp_path / "workspaces",
        source_store=store,
        ledger=ledger,
    )
    return primary, store, captured, ledger, coordinator


def _report(store: SourceTreeStore, status: str = "passed"):
    return store.put_bytes(
        canonical_json(
            {"schema": "daedalus-test-attempt-report/1", "status": status}
        ).encode("ascii")
    )


def test_start_is_persisted_before_external_materialization_and_primary_is_unchanged(tmp_path) -> None:
    primary, _store, captured, ledger, coordinator = _environment(tmp_path)
    before = digest_file_tree(primary)

    prepared = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )

    assert prepared.begin.execute is True
    assert prepared.workspace is not None
    assert coordinator.workspace_parent in prepared.workspace.parents
    assert primary not in prepared.workspace.parents
    assert prepared.workspace.joinpath("src/event.py").read_text(encoding="utf-8").endswith(
        "voltage = 5\n"
    )
    assert digest_file_tree(primary) == before
    assert ledger.pending() == (prepared.begin.start,)


def test_pending_restart_never_reexecutes_or_rematerializes(tmp_path) -> None:
    _primary_root, _store, captured, ledger, coordinator = _environment(tmp_path)
    attempt = _attempt()
    first = coordinator.prepare(
        attempt,
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )
    assert first.workspace is not None
    marker = first.workspace / "runtime-marker.txt"
    marker.write_text("must survive pending replay\n", encoding="utf-8")

    replay = coordinator.prepare(
        attempt,
        captured,
        start_id="start-attempt-1",
        started_at=LATER,
    )

    assert replay.begin.execute is False
    assert replay.begin.pending_reconciliation is True
    assert replay.workspace is None
    assert marker.read_text(encoding="utf-8") == "must survive pending replay\n"
    assert len(ledger.pending()) == 1


def test_terminal_replay_returns_persisted_receipt_without_workspace(tmp_path) -> None:
    _primary_root, store, captured, ledger, coordinator = _environment(tmp_path)
    attempt = _attempt()
    first = coordinator.prepare(
        attempt,
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )
    assert first.workspace is not None
    first.workspace.joinpath("src/event.py").write_text(
        "class Event:\n    bias_voltage = 5\n",
        encoding="utf-8",
    )
    candidate = store.capture_tree(
        first.workspace,
        tree_id="candidate-tree-1",
        source_revision=REVISION,
        origin="tests.isolated-attempt-candidate",
        created_at=LATER,
        trace_id=attempt.attempt_id,
    )
    completion = ledger.complete(
        first.begin.start,
        receipt_id="terminal-attempt-1",
        outcome="succeeded",
        report=_report(store),
        candidate_tree=candidate,
        completed_at=LATER,
    )

    replay = coordinator.prepare(
        attempt,
        captured,
        start_id="start-attempt-1",
        started_at="2026-08-03T21:32:00+00:00",
    )

    assert replay.begin.execute is False
    assert replay.workspace is None
    assert replay.begin.completion == completion
    assert ledger.pending() == ()


def test_terminal_completion_is_idempotent_across_new_completion_timestamp(tmp_path) -> None:
    _primary_root, store, captured, ledger, coordinator = _environment(tmp_path)
    prepared = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )
    report = _report(store, "failed")
    first = ledger.complete(
        prepared.begin.start,
        receipt_id="terminal-attempt-1",
        outcome="failed",
        report=report,
        candidate_tree=None,
        completed_at=LATER,
    )
    second = ledger.complete(
        prepared.begin.start,
        receipt_id="terminal-attempt-1",
        outcome="failed",
        report=report,
        candidate_tree=None,
        completed_at="2026-08-03T21:35:00+00:00",
    )
    assert second == first


def test_changed_replay_material_is_refused(tmp_path) -> None:
    _primary_root, _store, captured, ledger, coordinator = _environment(tmp_path)
    coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )
    with pytest.raises(AttemptReplay, match="different material"):
        coordinator.prepare(
            _attempt(),
            captured,
            start_id="different-start-id",
            started_at=LATER,
        )


def test_success_requires_candidate_and_candidate_revision_must_bind(tmp_path) -> None:
    _primary_root, store, captured, ledger, coordinator = _environment(tmp_path)
    prepared = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )
    with pytest.raises(ValueError, match="successful attempt"):
        ledger.complete(
            prepared.begin.start,
            receipt_id="terminal-attempt-1",
            outcome="succeeded",
            report=_report(store),
            candidate_tree=None,
            completed_at=LATER,
        )
    foreign = store.capture_tree(
        prepared.workspace,
        tree_id="candidate-tree-foreign",
        source_revision="b" * 40,
        origin="tests.isolated-attempt-candidate",
        created_at=LATER,
    )
    with pytest.raises(AttemptBindingMismatch, match="candidate source tree revision"):
        ledger.complete(
            prepared.begin.start,
            receipt_id="terminal-attempt-1",
            outcome="failed",
            report=_report(store),
            candidate_tree=foreign,
            completed_at=LATER,
        )


def test_new_attempt_identity_is_required_after_failure(tmp_path) -> None:
    _primary_root, store, captured, ledger, coordinator = _environment(tmp_path)
    failed = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=NOW,
    )
    ledger.complete(
        failed.begin.start,
        receipt_id="terminal-attempt-1",
        outcome="failed",
        report=_report(store, "failed"),
        candidate_tree=None,
        completed_at=LATER,
    )
    old = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=LATER,
    )
    assert old.begin.execute is False
    assert old.begin.completion.receipt.outcome == "failed"

    restarted = coordinator.prepare(
        _attempt(attempt_id="attempt-2"),
        captured,
        start_id="start-attempt-2",
        started_at=LATER,
    )
    assert restarted.begin.execute is True
    assert restarted.workspace is not None
    assert restarted.workspace != failed.workspace


def test_only_one_concurrent_begin_can_execute(tmp_path) -> None:
    _primary_root, _store, captured, ledger, coordinator = _environment(tmp_path)
    attempt = _attempt()

    def begin(_index: int):
        return ledger.begin(
            attempt,
            captured,
            start_id="start-attempt-1",
            workspace_parent_sha256=coordinator.workspace_parent_sha256,
            workspace_relative_path=f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}",
            started_at=NOW,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(begin, range(8)))
    assert sum(result.execute for result in results) == 1
    assert all(result.start == results[0].start for result in results)


def test_workspace_parent_must_be_disjoint_from_primary_and_cas(tmp_path) -> None:
    primary = _primary(tmp_path)
    external_store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "attempts.sqlite3")
    with pytest.raises(AttemptWorkspaceError, match="primary checkout"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=primary / ".attempts",
            source_store=external_store,
            ledger=ledger,
        )
    with pytest.raises(AttemptWorkspaceError, match="source-tree store"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=external_store.root / "workspaces",
            source_store=external_store,
            ledger=ledger,
        )


def test_stale_input_revision_refuses_before_start(tmp_path) -> None:
    primary, store, _captured, ledger, coordinator = _environment(tmp_path)
    stale = store.capture_tree(
        primary,
        tree_id="stale-tree",
        source_revision="b" * 40,
        origin="tests.stale-input",
        created_at=NOW,
    )
    with pytest.raises(AttemptBindingMismatch, match="input source tree revision"):
        coordinator.prepare(
            _attempt(),
            stale,
            start_id="start-attempt-1",
            started_at=NOW,
        )
    assert ledger.pending() == ()


def test_materialization_failure_is_terminalized_but_process_abort_remains_pending(
    tmp_path, monkeypatch
) -> None:
    _primary_root, store, captured, ledger, coordinator = _environment(tmp_path)

    def fail_materialization(*_args, **_kwargs):
        raise OSError("simulated filesystem refusal")

    monkeypatch.setattr(store, "materialize_tree", fail_materialization)
    with pytest.raises(AttemptWorkspaceError, match="terminalized"):
        coordinator.prepare(
            _attempt(),
            captured,
            start_id="start-attempt-1",
            started_at=NOW,
        )
    replay = coordinator.prepare(
        _attempt(),
        captured,
        start_id="start-attempt-1",
        started_at=LATER,
    )
    assert replay.begin.completion.receipt.outcome == "faulted"
    assert ledger.pending() == ()

    second = _attempt(attempt_id="attempt-2")

    def abort_materialization(*_args, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(store, "materialize_tree", abort_materialization)
    with pytest.raises(KeyboardInterrupt):
        coordinator.prepare(
            second,
            captured,
            start_id="start-attempt-2",
            started_at=LATER,
        )
    assert [start.attempt_id for start in ledger.pending()] == ["attempt-2"]
