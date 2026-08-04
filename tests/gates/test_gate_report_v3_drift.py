from __future__ import annotations

from pathlib import Path

import pytest

import daedalus.gates.report_v3 as report_v3
from daedalus.gates.report import GateReport
from daedalus.gates.report_v3 import GateReportV3, GateReportV3Error


REVISION = "1" * 40
SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ("b" * 64, "c" * 64, 1, 2, ("path.py:1:0:write",), ())


def _base(*, diagnostics=()) -> GateReport:
    return GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256=SHA,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="d" * 64,
        diagnostics=diagnostics,
    )


def test_base_report_drift_refuses_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    reports = iter((_base(), _base(diagnostics=("drift",))))
    monkeypatch.setattr(report_v3, "_build_base_report", lambda *args, **kwargs: next(reports))
    monkeypatch.setattr(report_v3, "_repository_write_evidence", lambda *args, **kwargs: INVENTORY)
    with pytest.raises(GateReportV3Error, match="base GateReport-v2 changed"):
        report_v3.build_gate0_report_v3(ROOT, source_revision=REVISION)


def test_repository_inventory_drift_refuses_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventories = iter(
        (
            INVENTORY,
            ("e" * 64, "f" * 64, 1, 2, ("path.py:1:0:write",), ()),
        )
    )
    monkeypatch.setattr(report_v3, "_build_base_report", lambda *args, **kwargs: _base())
    monkeypatch.setattr(
        report_v3,
        "_repository_write_evidence",
        lambda *args, **kwargs: next(inventories),
    )
    with pytest.raises(GateReportV3Error, match="inventory changed"):
        report_v3.build_gate0_report_v3(ROOT, source_revision=REVISION)


def test_mutable_iterable_inputs_are_snapshotted_before_repeated_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, ...]] = []

    def base_builder(*args, primary_checkout_mutations, **kwargs):
        observed.append(primary_checkout_mutations)
        return _base()

    monkeypatch.setattr(report_v3, "_build_base_report", base_builder)
    monkeypatch.setattr(report_v3, "_repository_write_evidence", lambda *args, **kwargs: INVENTORY)
    mutations = (row for row in ("first", "second"))
    report = report_v3.build_gate0_report_v3(
        ROOT,
        source_revision=REVISION,
        primary_checkout_mutations=mutations,
    )
    assert type(report) is GateReportV3
    assert observed == [("first", "second"), ("first", "second")]
    assert report.primary_checkout_mutations == ()


def test_non_exact_base_report_refuses_before_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subclass = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256=SHA,
        security_boundary_claimed=False,
    )
    monkeypatch.setattr(report_v3, "build_gate0_report", lambda *args, **kwargs: subclass)
    with pytest.raises(GateReportV3Error, match="non-exact report"):
        report_v3._build_base_report(
            ROOT,
            source_revision=REVISION,
            runtime_receipts=(),
            fault_results=None,
            primary_checkout_mutations=(),
            security_boundary_claimed=False,
        )


def test_direct_non_json_payload_is_normalized_to_v3_error() -> None:
    report = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256=SHA,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="d" * 64,
        repository_write_inventory_sha256="b" * 64,
        repository_write_scan_input_sha256="c" * 64,
        repository_write_files_scanned=1,
        repository_write_inventory_generation=2,
    )
    payload = report.to_dict()
    payload["diagnostics"] = [object()]
    with pytest.raises(GateReportV3Error, match="canonical JSON data"):
        GateReportV3.from_dict(payload)
