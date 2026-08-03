from __future__ import annotations

import inspect
from pathlib import Path

from daedalus.spine import effect_boundary as boundary
from daedalus.spine.effect_boundary import Effect, Surface, Wiring


ROOT = Path(__file__).resolve().parents[2]
TARGETS = {
    "daedalus.kernel.attempt_ledger:AttemptLedger.begin": (
        "python.attempt_lifecycle_begin",
        ("record_intent",),
    ),
    "daedalus.kernel.attempt_ledger:AttemptLedger.complete": (
        "python.attempt_lifecycle_complete",
        ("mark_completed",),
    ),
    "daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare": (
        "python.attempt_workspace_prepare",
        ("begin", "materialize_tree"),
    ),
}


def _rows_by_target():
    return {row.target: row for row in boundary.ENTRYPOINTS}


def test_attempt_lifecycle_targets_have_one_honest_registry_owner() -> None:
    rows = _rows_by_target()
    for target, (row_id, anchors) in TARGETS.items():
        matching = [row for row in boundary.ENTRYPOINTS if row.target == target]
        assert len(matching) == 1
        row = rows[target]
        assert row.id == row_id
        assert row.surface is Surface.PYTHON
        assert row.effects == (Effect.FILESYSTEM_WRITE,)
        assert row.guard_contracts == (
            "spine.intent_ledger",
            "containment.attempt",
        )
        assert row.wiring is Wiring.LOCAL_GUARDS
        assert tuple(anchor.call for anchor in row.anchors) == anchors
        assert row.discoverable is True
        assert row.migration


def test_static_inventory_discovers_all_attempt_lifecycle_boundaries() -> None:
    discoveries, scan_findings = boundary.discover_entrypoints(ROOT)
    discovered = {row.target: row for row in discoveries}
    for target in TARGETS:
        assert target in discovered
        row = discovered[target]
        assert row.surface is Surface.PYTHON
        assert row.effects == (Effect.FILESYSTEM_WRITE,)
    assert not [
        finding
        for finding in scan_findings
        if finding.severity == "blocker" and finding.subject in TARGETS
    ]


def test_conformance_has_no_registration_or_anchor_blocker_for_attempt_lifecycle() -> None:
    report = boundary.check_conformance(ROOT)
    relevant = [
        finding
        for finding in report.findings
        if finding.subject in TARGETS
        or finding.subject in {value[0] for value in TARGETS.values()}
    ]
    assert not [finding for finding in relevant if finding.severity == "blocker"]


def test_source_classifier_names_attempt_authorities_explicitly() -> None:
    class_source = inspect.getsource(boundary._class_surface)
    method_source = inspect.getsource(boundary._surface_for_function)
    assert 'model.module == "daedalus.kernel.attempt_ledger"' in class_source
    assert 'class_name == "AttemptLedger"' in class_source
    assert 'model.module == "daedalus.kernel.attempt_workspace"' in class_source
    assert 'class_name == "IsolatedAttemptCoordinator"' in class_source
    assert 'qualname in {"AttemptLedger.begin", "AttemptLedger.complete"}' in method_source
    assert 'qualname == "IsolatedAttemptCoordinator.prepare"' in method_source


def test_registration_does_not_pretend_attempt_execution_is_central() -> None:
    rows = _rows_by_target()
    for target in TARGETS:
        row = rows[target]
        assert row.wiring is not Wiring.CENTRAL
        assert "EffectLease" in row.migration
        assert "sandbox" in row.migration.casefold()
