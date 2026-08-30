# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import inspect
import json
from pathlib import Path

from daedalus.spine import effect_boundary as boundary
from daedalus.spine.effect_boundary import Effect, Surface, Wiring


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs" / "work-packets" / "G0-ATT-13B_EFFECT_INVENTORY.json"
TARGETS = {
    "daedalus.kernel.attempt_ledger:AttemptLedger.begin": (
        "kernel.attempt.begin",
        ("spine.intent_ledger",),
        ("record_intent",),
    ),
    "daedalus.kernel.attempt_ledger:AttemptLedger.complete": (
        "kernel.attempt.complete",
        ("spine.intent_ledger",),
        ("mark_completed",),
    ),
    "daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare": (
        "kernel.attempt.prepare",
        ("spine.intent_ledger", "containment.attempt"),
        ("begin", "materialize_tree"),
    ),
}


def _rows_by_target():
    return {row.target: row for row in boundary.ENTRYPOINTS}


def test_attempt_lifecycle_targets_have_one_honest_registry_owner() -> None:
    rows = _rows_by_target()
    for target, (row_id, guards, anchors) in TARGETS.items():
        matching = [row for row in boundary.ENTRYPOINTS if row.target == target]
        assert len(matching) == 1
        row = rows[target]
        assert row.id == row_id
        assert row.surface is Surface.PYTHON
        assert row.effects == (Effect.FILESYSTEM_WRITE,)
        assert row.guard_contracts == guards
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
    ids = {value[0] for value in TARGETS.values()}
    relevant = [
        finding
        for finding in report.findings
        if finding.subject in TARGETS or finding.subject in ids
    ]
    assert not [finding for finding in relevant if finding.severity == "blocker"]
    gaps = {
        finding.subject
        for finding in relevant
        if finding.code == "gate0.not_central" and finding.severity == "gap"
    }
    assert gaps == ids
    assert report.gate0_closed is False


def test_parent_blocker_is_resolved_only_as_local_guards() -> None:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert review["status"] == "resolved_at_local_guards"
    assert review["security_boundary_claimed"] is False
    assert review["findings"] == []
    resolved = {row["target"]: row for row in review["resolved_findings"]}
    assert set(resolved) == set(TARGETS)
    for target, (row_id, guards, anchors) in TARGETS.items():
        row = resolved[target]
        assert row["registry_id"] == row_id
        assert row["required_guards"] == list(guards)
        assert row["anchors"] == list(anchors)
        assert row["current_wiring"] == "local_guards"
        assert row["gate0_target_wiring"] == "central"


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
