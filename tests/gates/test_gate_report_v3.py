# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from daedalus.gates.report import GateReport
from daedalus.gates.report_v3 import (
    GateReportV3,
    GateReportV3Error,
    assert_monotonic_v3,
    build_gate0_report_v3,
    load_gate_report_v3,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2Error,
)


REVISION = "1" * 40
OTHER_REVISION = "2" * 40
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
ROOT = Path(__file__).resolve().parents[2]


def _clean_report(**changes) -> GateReportV3:
    report = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256=SHA_A,
        security_boundary_claimed=True,
        event_store_writer_inventory_sha256=SHA_B,
        owner_approval_enforced=True,
        repository_write_inventory_sha256=SHA_C,
        repository_write_scan_input_sha256="d" * 64,
        repository_write_files_scanned=1,
        repository_write_inventory_generation=2,
        repository_write_inventory_schema=(
            "daedalus-gate0-repository-write-inventory/2"
        ),
        # Pin moved with the wire at daedalus-gate-report/5: a closable report
        # now has to declare which chain classified its surfaces and a census
        # that accounts for every one of them.
        repository_write_surfaces_total=1,
        repository_write_classification_schema=(
            "daedalus-gate0-repository-write-classification/2"
        ),
        repository_write_surface_verdicts=("cleared:central:1",),
    )
    return dataclasses.replace(report, **changes)


def test_complete_v3_report_can_close_only_with_repository_write_evidence() -> None:
    report = _clean_report()
    assert report.closed is True
    assert report.blockers == ()
    payload = report.to_dict()
    assert payload["schema"] == "daedalus-gate-report/5"
    assert payload["closed"] is True
    assert payload["repository_write_inventory_sha256"] == SHA_C
    assert payload["repository_write_scan_input_sha256"] == "d" * 64
    assert payload["repository_write_files_scanned"] == 1
    assert payload["repository_write_inventory_generation"] == 2
    assert payload["repository_write_surfaces_total"] == 1
    assert payload["repository_write_classification_schema"] == (
        "daedalus-gate0-repository-write-classification/2"
    )
    assert payload["repository_write_surface_verdicts"] == ["cleared:central:1"]
    assert payload["repository_write_failures"] == []
    assert len(payload["report_sha256"]) == 64
    assert GateReportV3.from_dict(payload) == report


@pytest.mark.parametrize(
    "changes,expected",
    [
        (
            {"repository_write_inventory_sha256": None},
            "repository_write_inventory_sha256:missing",
        ),
        (
            {"repository_write_scan_input_sha256": None},
            "repository_write_scan_input_sha256:missing",
        ),
        (
            {"repository_write_files_scanned": 0},
            "repository_write_files_scanned:missing",
        ),
        (
            {"repository_write_inventory_generation": 0},
            "repository_write_inventory_generation:unsupported:0",
        ),
        (
            {"repository_write_inventory_generation": 3},
            "repository_write_inventory_generation:unsupported:3",
        ),
        (
            {"repository_write_failures": ("path.py:1:0:write",)},
            "repository_write_failures:path.py:1:0:write",
        ),
        (
            {"repository_write_classification_schema": None},
            "repository_write_classification_schema:unsupported:None",
        ),
        (
            {"repository_write_surface_verdicts": ()},
            "repository_write_surface_verdicts:inconsistent:0:1",
        ),
        (
            {"repository_write_surface_verdicts": ("cleared:central",)},
            "repository_write_surface_verdicts:malformed:cleared:central",
        ),
    ],
)
def test_missing_or_blocking_repository_write_evidence_prevents_closure(
    changes,
    expected: str,
) -> None:
    report = _clean_report(**changes)
    assert report.closed is False
    assert expected in report.blockers
    assert report.to_dict()["closed"] is False


def test_repository_write_failures_are_canonical_and_part_of_digest() -> None:
    report = _clean_report(
        repository_write_failures=("z.py:2:0:write", "a.py:1:0:write", "z.py:2:0:write")
    )
    assert report.repository_write_failures == (
        "a.py:1:0:write",
        "z.py:2:0:write",
    )
    payload = report.to_dict()
    assert payload["repository_write_failures"] == [
        "a.py:1:0:write",
        "z.py:2:0:write",
    ]
    clean = _clean_report()
    assert payload["report_sha256"] != clean.to_dict()["report_sha256"]


def test_v2_payload_is_not_release_laundered_as_v3() -> None:
    v2 = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256=SHA_A,
        security_boundary_claimed=True,
        event_store_writer_inventory_sha256=SHA_B,
        owner_approval_enforced=True,
    )
    assert v2.closed is True
    with pytest.raises(GateReportV3Error, match="fields are not exact"):
        GateReportV3.from_dict(v2.to_dict())


@pytest.mark.parametrize(
    "mutator,match",
    [
        (lambda body: body.update(extra="forbidden"), "fields are not exact"),
        (lambda body: body.pop("repository_write_inventory_sha256"), "fields are not exact"),
        (lambda body: body.update(schema="daedalus-gate-report/2"), "schema"),
        (lambda body: body.update(closed=False), "digest mismatch"),
        (lambda body: body.update(report_sha256="0" * 64), "digest mismatch"),
        (
            lambda body: body.update(repository_write_files_scanned=True),
            "must be an integer",
        ),
        (
            lambda body: body.update(repository_write_failures=["z", "a"]),
            "sorted and unique",
        ),
    ],
)
def test_malformed_or_noncanonical_v3_payload_refuses(mutator, match: str) -> None:
    payload = _clean_report().to_dict()
    mutator(payload)
    if match != "digest mismatch" and payload.get("report_sha256"):
        body = dict(payload)
        body.pop("report_sha256")
        payload["report_sha256"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()
    with pytest.raises(GateReportV3Error, match=match):
        GateReportV3.from_dict(payload)


def test_strict_loader_rejects_duplicate_nonfinite_non_utf8_and_oversize(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    payload = _clean_report().to_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    path.write_text(canonical, encoding="utf-8")
    assert load_gate_report_v3(path) == _clean_report()

    path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(GateReportV3Error, match="duplicate"):
        load_gate_report_v3(path)

    path.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(GateReportV3Error, match="non-finite"):
        load_gate_report_v3(path)

    path.write_bytes(b"\xff\xfe")
    with pytest.raises(GateReportV3Error, match="UTF-8"):
        load_gate_report_v3(path)

    path.write_bytes(b"{" + b" " * (4 * 1024 * 1024) + b"}")
    with pytest.raises(GateReportV3Error, match="maximum size"):
        load_gate_report_v3(path)


def test_monotonic_v3_detects_new_repository_write_blocker() -> None:
    baseline = _clean_report()
    current = _clean_report(
        repository_write_failures=("provider_observation.py:write",)
    )
    assert assert_monotonic_v3(current, baseline) == (
        "repository_write_failures:provider_observation.py:write",
    )
    with pytest.raises(GateReportV3Error, match="exact GateReportV3"):
        assert_monotonic_v3(current, GateReport(**{
            field.name: getattr(baseline, field.name)
            for field in dataclasses.fields(GateReport)
        }))


def test_revision_label_is_part_of_v3_report_identity() -> None:
    first = _clean_report()
    stale = dataclasses.replace(first, source_revision=OTHER_REVISION)
    assert stale.repository_write_inventory_sha256 == first.repository_write_inventory_sha256
    assert stale.to_dict()["report_sha256"] != first.to_dict()["report_sha256"]


def test_builder_binds_live_canonical_repository_write_inventory() -> None:
    report = build_gate0_report_v3(ROOT, source_revision=REVISION)
    assert report.repository_write_inventory_sha256 is not None
    assert report.repository_write_scan_input_sha256 is not None
    assert report.repository_write_files_scanned > 0
    assert report.repository_write_inventory_generation == 2
    assert report.repository_write_failures
    assert report.closed is False


def test_builder_fails_closed_when_repository_write_inventory_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args, **kwargs):
        raise RepositoryWriteInventoryV2Error("forced scanner refusal")

    monkeypatch.setattr(
        "daedalus.gates.report_v3.scan_repository_write_surfaces_v2",
        refuse,
    )
    report = build_gate0_report_v3(ROOT, source_revision=REVISION)
    assert report.repository_write_inventory_sha256 is None
    assert report.repository_write_scan_input_sha256 is None
    assert report.repository_write_files_scanned == 0
    assert report.repository_write_inventory_generation == 0
    assert report.repository_write_failures == ("inventory-refused",)
    assert "blocker:repository_write_inventory:refused" in report.diagnostics
    assert report.closed is False
