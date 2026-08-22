"""The Gate-0 report declares which inventory schema produced its evidence.

Phase 4 of `docs/inventory/2026-08-21/GIGA_PLAN_2026-08-22.md` computes closure
from `inventory_only == 0 && blocked == 0 && executed == 24 && scanner_error ==
0`.  Before this file, `scanner_error` was not a field of any emitted report
(the pre-ruling census searched for it and found nothing: see
`docs/inventory/2026-08-21/preruling/DECISION_PACKAGE_2026-08-22.md` row 5), and
the schema of the inventory behind the evidence was never named in the report.

The HEAD assertion here deliberately does NOT spawn the reporter.  Measured on
this host: the record census below takes 14.5s, one generation-2 scan takes
49.2s, and the full `scripts/report_gate0_v3.py` run builds the base report
twice and scans twice (minutes).  The census is the exact property that makes
`scanner_error` zero -- an injective record identity -- so it is the cheapest
honest guard.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.gates import report_v3
from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates import repository_write_inventory as inventory


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "configs" / "schemas" / "gate-report-v5.schema.json"
REVISION = "1" * 40
SHA = "a" * 64


def _report(**changes) -> GateReportV3:
    report = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256=SHA,
        security_boundary_claimed=True,
        event_store_writer_inventory_sha256="b" * 64,
        owner_approval_enforced=True,
        repository_write_inventory_sha256="c" * 64,
        repository_write_scan_input_sha256="d" * 64,
        repository_write_files_scanned=1,
        repository_write_inventory_generation=2,
        repository_write_inventory_schema=report_v3._INVENTORY_SCHEMA,
        # Moved with the wire at daedalus-gate-report/5: the counters are now
        # a classified census, so a closable report has to name the chain that
        # classified and account for every syntactic surface.
        repository_write_surfaces_total=1,
        repository_write_classification_schema=report_v3._CLASSIFICATION_SCHEMA,
        repository_write_surface_verdicts=("cleared:central:1",),
    )
    if not changes:
        return report
    return type(report)(
        **{
            **{
                field: getattr(report, field)
                for field in report.__dataclass_fields__
            },
            **changes,
        }
    )


def test_report_wire_shape_moved_with_the_added_counters() -> None:
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert payload["additionalProperties"] is False
    assert payload["properties"]["schema"]["const"] == report_v3._SCHEMA
    assert report_v3._SCHEMA == "daedalus-gate-report/5"
    assert set(payload["required"]) == set(report_v3._V3_FIELDS)
    for field in (
        "repository_write_inventory_schema",
        "repository_write_scanner_error",
        "repository_write_surfaces_total",
        "repository_write_classification_schema",
        "repository_write_surface_verdicts",
    ):
        assert field in payload["required"]
        assert field in payload["properties"]


def test_report_declares_the_inventory_schema_it_observed() -> None:
    body = _report().to_dict()
    assert (
        body["repository_write_inventory_schema"]
        == "daedalus-gate0-repository-write-inventory/2"
    )
    assert body["repository_write_scanner_error"] == 0
    assert body["closed"] is True
    assert GateReportV3.from_dict(body) == _report()


@pytest.mark.parametrize(
    "changes,row",
    [
        (
            {"repository_write_scanner_error": 1},
            "repository_write_scanner_error:1",
        ),
        (
            {"repository_write_inventory_schema": None},
            "repository_write_inventory_schema:unsupported:None",
        ),
        (
            {
                "repository_write_inventory_schema": (
                    "daedalus-gate0-repository-write-inventory/1"
                )
            },
            "repository_write_inventory_schema:unsupported:"
            "daedalus-gate0-repository-write-inventory/1",
        ),
    ],
)
def test_an_undeclared_or_failed_scan_cannot_close_the_gate(
    changes: dict[str, object],
    row: str,
) -> None:
    report = _report(**changes)
    assert row in report.blockers
    assert report.closed is False


def test_scanner_error_is_zero_at_head_because_record_identity_is_injective() -> None:
    """Structural: 14.5s census, not the multi-minute reporter (see module doc)."""

    package_root = ROOT / "daedalus"
    files = inventory._production_files(package_root)
    records = [
        site
        for path in files
        for site in inventory._callsites_for_file(ROOT, package_root, path)
    ]
    assert len(records) == len(set(records)), (
        "duplicate callsite records at HEAD: the generation-1 container will "
        "refuse and every Gate-0 counter is lost"
    )
    positions = {(site.path, site.line, site.column) for site in records}
    assert len(positions) == len(records), (
        "two records share one source position at HEAD: the generation-2 "
        "composition will refuse"
    )
    assert inventory._ambiguity_hint(records) == ""
