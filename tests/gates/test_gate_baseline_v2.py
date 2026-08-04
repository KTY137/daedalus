from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from daedalus.gates.baseline import (
    GateBaseline,
    GateBaselineBindingError,
    GateBaselineError,
    GateMonotonicityReceipt,
    assess_gate0_monotonicity,
    create_gate0_baseline,
    load_current_gate_report,
    load_gate0_baseline,
    load_gate0_monotonicity_receipt,
)
from daedalus.gates.baseline_verifier import (
    GateMonotonicityBlocked,
    verify_gate0_monotonicity_receipt,
)
from daedalus.gates.report import GateReport


BASE_REVISION = "a" * 40
BASE_TREE = "b" * 40
CURRENT_REVISION = "c" * 40
CURRENT_TREE = "d" * 40
REGISTRY = "e" * 64
WRITERS = "f" * 64
CREATED = "2026-08-04T00:00:00+00:00"
ASSESSED = "2026-08-04T00:05:00+00:00"


def _report(
    *,
    revision: str = BASE_REVISION,
    unguarded: tuple[str, ...] = ("python.legacy",),
    writer_failures: tuple[str, ...] = (),
    inventory: str | None = WRITERS,
    security: bool = False,
    owner: bool = True,
) -> GateReport:
    return GateReport(
        gate=0,
        source_revision=revision,
        registry_sha256=REGISTRY,
        security_boundary_claimed=security,
        unguarded_entrypoints=unguarded,
        event_store_writer_inventory_sha256=inventory,
        event_store_writer_failures=writer_failures,
        owner_approval_enforced=owner,
    )


def _baseline(report: GateReport | None = None) -> GateBaseline:
    return create_gate0_baseline(
        report or _report(),
        baseline_id="gate0-baseline-2026-08-04",
        source_tree_revision=BASE_TREE,
        created_at=CREATED,
    )


def _assess(
    baseline: GateBaseline,
    current: GateReport,
    **changes,
) -> GateMonotonicityReceipt:
    values = {
        "expected_baseline_sha256": baseline.digest,
        "current_source_tree_revision": CURRENT_TREE,
        "assessment_id": "gate0-monotonicity-1",
        "assessed_at": ASSESSED,
    }
    values.update(changes)
    return assess_gate0_monotonicity(baseline, current, **values)


def test_baseline_round_trip_binds_report_revision_tree_and_blockers() -> None:
    report = _report()
    baseline = _baseline(report)

    assert baseline.source_revision == BASE_REVISION
    assert baseline.source_tree_revision == BASE_TREE
    assert baseline.gate_report_sha256 == report.to_dict()["report_sha256"]
    assert baseline.registry_sha256 == REGISTRY
    assert baseline.event_store_writer_inventory_sha256 == WRITERS
    assert baseline.blockers == report.blockers
    assert GateBaseline.from_dict(baseline.to_dict()) == baseline
    assert len(baseline.digest) == 64


def test_baseline_requires_writer_inventory_and_exact_revisions() -> None:
    with pytest.raises(GateBaselineBindingError, match="writer inventory"):
        _baseline(_report(inventory=None))
    with pytest.raises(ValueError, match="source_tree_revision"):
        create_gate0_baseline(
            _report(),
            baseline_id="gate0-baseline",
            source_tree_revision="working-tree",
            created_at=CREATED,
        )


def test_baseline_digest_and_blocker_set_tampering_refuse() -> None:
    baseline = _baseline()
    payload = baseline.to_dict()
    payload["baseline_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        GateBaseline.from_dict(payload)

    payload = baseline.to_dict()
    payload["blockers"] = []
    with pytest.raises(ValueError, match="blocker_set_sha256"):
        GateBaseline.from_dict(payload)


def test_monotonicity_passes_when_blockers_are_retained_or_resolved() -> None:
    baseline = _baseline()
    current = _report(
        revision=CURRENT_REVISION,
        unguarded=(),
        security=False,
    )
    receipt = _assess(baseline, current)

    assert receipt.status == "passed"
    assert receipt.new_blockers == ()
    assert "unguarded_entrypoints:python.legacy" in receipt.resolved_blockers
    assert "security_boundary_claimed:false" in receipt.retained_blockers
    assert receipt.current_source_revision == CURRENT_REVISION
    assert receipt.current_source_tree_revision == CURRENT_TREE
    assert GateMonotonicityReceipt.from_dict(receipt.to_dict()) == receipt
    assert verify_gate0_monotonicity_receipt(
        receipt,
        baseline,
        current,
        expected_baseline_sha256=baseline.digest,
        current_source_tree_revision=CURRENT_TREE,
        require_monotonic=True,
    ) == receipt


def test_new_writer_blocker_fails_monotonicity() -> None:
    baseline = _baseline()
    writer_failure = (
        "daedalus/app.py:10:4:legacy_direct:daedalus.spine.SpineLedger"
    )
    current = _report(
        revision=CURRENT_REVISION,
        writer_failures=(writer_failure,),
    )
    receipt = _assess(baseline, current)

    assert receipt.status == "failed"
    assert receipt.new_blockers == (
        f"event_store_writer_failures:{writer_failure}",
    )
    with pytest.raises(GateMonotonicityBlocked, match="new Gate blockers"):
        verify_gate0_monotonicity_receipt(
            receipt,
            baseline,
            current,
            expected_baseline_sha256=baseline.digest,
            current_source_tree_revision=CURRENT_TREE,
            require_monotonic=True,
        )


def test_missing_current_writer_inventory_is_a_new_blocker() -> None:
    baseline = _baseline()
    current = _report(
        revision=CURRENT_REVISION,
        inventory=None,
    )
    receipt = _assess(baseline, current)
    assert receipt.status == "failed"
    assert (
        "event_store_writer_inventory_sha256:missing" in receipt.new_blockers
    )


def test_expected_baseline_digest_is_mandatory_and_exact() -> None:
    baseline = _baseline()
    current = _report(revision=CURRENT_REVISION)
    with pytest.raises(GateBaselineBindingError, match="expected baseline"):
        _assess(
            baseline,
            current,
            expected_baseline_sha256="0" * 64,
        )
    with pytest.raises(ValueError, match="expected_baseline_sha256"):
        _assess(
            baseline,
            current,
            expected_baseline_sha256="bad",
        )


def test_receipt_verifier_recomputes_every_partition_and_binding() -> None:
    baseline = _baseline()
    current = _report(revision=CURRENT_REVISION, unguarded=())
    receipt = _assess(baseline, current)

    forged = dataclasses.replace(
        receipt,
        retained_blockers=(),
        resolved_blockers=tuple(
            sorted(
                set(receipt.resolved_blockers)
                | set(receipt.retained_blockers)
            )
        ),
    )
    with pytest.raises(GateBaselineBindingError, match="recomputed evidence"):
        verify_gate0_monotonicity_receipt(
            forged,
            baseline,
            current,
            expected_baseline_sha256=baseline.digest,
            current_source_tree_revision=CURRENT_TREE,
        )

    with pytest.raises(GateBaselineBindingError, match="recomputed evidence"):
        verify_gate0_monotonicity_receipt(
            receipt,
            baseline,
            current,
            expected_baseline_sha256=baseline.digest,
            current_source_tree_revision="9" * 40,
        )


def test_receipt_status_and_partition_overlap_are_derived() -> None:
    receipt = _assess(_baseline(), _report(revision=CURRENT_REVISION))
    with pytest.raises(ValueError, match="status"):
        dataclasses.replace(receipt, status="failed")
    with pytest.raises(ValueError, match="disjoint"):
        dataclasses.replace(
            receipt,
            new_blockers=receipt.retained_blockers,
            status="failed",
        )


def test_baseline_and_receipt_file_loaders_are_strict(tmp_path: Path) -> None:
    baseline = _baseline()
    receipt = _assess(baseline, _report(revision=CURRENT_REVISION))
    baseline_path = tmp_path / "baseline.json"
    receipt_path = tmp_path / "receipt.json"
    baseline_path.write_text(json.dumps(baseline.to_dict()), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt.to_dict()), encoding="utf-8")
    assert load_gate0_baseline(baseline_path) == baseline
    assert load_gate0_monotonicity_receipt(receipt_path) == receipt

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_gate0_baseline(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_gate0_baseline(nonfinite)

    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff")
    with pytest.raises(GateBaselineError, match="UTF-8"):
        load_gate0_baseline(binary)


def test_current_report_loader_refuses_v1_without_writer_inventory(tmp_path: Path) -> None:
    report = _report()
    payload = report.to_dict()
    payload["event_store_writer_inventory_sha256"] = None
    payload["event_store_writer_failures"] = []
    payload["blockers"] = sorted(
        set(payload["blockers"])
        | {"event_store_writer_inventory_sha256:missing"}
    )
    body = dict(payload)
    body.pop("report_sha256")
    import hashlib

    payload["report_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(GateBaselineBindingError, match="must be v2"):
        load_current_gate_report(path)
