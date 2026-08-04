from __future__ import annotations

import pytest

from daedalus.gates.report_v3 import GateReportV3, GateReportV3Error


BASE = {
    "gate": 0,
    "source_revision": "1" * 40,
    "registry_sha256": "a" * 64,
    "security_boundary_claimed": False,
    "event_store_writer_inventory_sha256": "b" * 64,
    "repository_write_inventory_sha256": "c" * 64,
    "repository_write_scan_input_sha256": "d" * 64,
}


@pytest.mark.parametrize(
    "field",
    [
        "repository_write_files_scanned",
        "repository_write_inventory_generation",
    ],
)
def test_negative_repository_write_integer_refuses(field: str) -> None:
    values = {
        **BASE,
        "repository_write_files_scanned": 1,
        "repository_write_inventory_generation": 2,
        field: -1,
    }
    with pytest.raises(GateReportV3Error, match="non-negative integer"):
        GateReportV3(**values)


@pytest.mark.parametrize(
    "field",
    [
        "repository_write_files_scanned",
        "repository_write_inventory_generation",
    ],
)
def test_boolean_repository_write_integer_refuses(field: str) -> None:
    values = {
        **BASE,
        "repository_write_files_scanned": 1,
        "repository_write_inventory_generation": 2,
        field: True,
    }
    with pytest.raises(GateReportV3Error, match="non-negative integer"):
        GateReportV3(**values)
