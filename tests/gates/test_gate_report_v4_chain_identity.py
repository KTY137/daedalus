"""Small mutation anchors for mandatory GateReport-v4 chain identity."""
from __future__ import annotations

from daedalus.gates.report_v4 import GateReportV4
from daedalus.gates.repository_write_classification import CLASSIFICATION_SCHEMA


def _report(**overrides) -> GateReportV4:
    values = dict(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="c" * 64,
        owner_approval_enforced=False,
        repository_write_inventory_sha256="d" * 64,
        repository_write_scan_input_sha256="e" * 64,
        repository_write_files_scanned=1,
        repository_write_inventory_generation=2,
        repository_write_inventory_schema=(
            "daedalus-gate0-repository-write-inventory/2"
        ),
        repository_write_scanner_error=0,
        repository_write_surfaces_total=0,
        repository_write_classification_schema=CLASSIFICATION_SCHEMA,
        repository_write_surface_verdicts=(),
        repository_write_failures=(),
        repository_write_chain_result_schema=(
            "daedalus-gate0-repository-write-chain-result/1"
        ),
        repository_write_chain_result_sha256="f" * 64,
    )
    values.update(overrides)
    return GateReportV4(**values)


def test_chain_result_digest_is_mandatory() -> None:
    report = _report(repository_write_chain_result_sha256=None)
    assert "repository_write_chain_result_sha256:missing" in report.blockers


def test_chain_result_schema_is_exact() -> None:
    report = _report(repository_write_chain_result_schema="foreign/1")
    assert (
        "repository_write_chain_result_schema:unsupported:foreign/1"
        in report.blockers
    )
