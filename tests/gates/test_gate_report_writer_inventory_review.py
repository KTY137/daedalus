from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import daedalus.gates.report as report_module
from daedalus.gates.report import GateReport
from daedalus.spine.writer_inventory import WriterInventoryError


def _resign(payload: dict[str, object]) -> dict[str, object]:
    body = dict(payload)
    body.pop("report_sha256", None)
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    return payload


def _closed_report() -> GateReport:
    return GateReport(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256="c" * 64,
    )


def test_inventory_refusal_becomes_bound_gate_blockers(monkeypatch, tmp_path) -> None:
    def refuse(*args, **kwargs):
        raise WriterInventoryError("injected malformed source")

    monkeypatch.setattr(report_module, "scan_event_store_writers", refuse)
    digest, failures, diagnostics = report_module._writer_inventory_evidence(
        tmp_path,
        "a" * 40,
    )
    assert digest is None
    assert failures == ("inventory-refused",)
    assert diagnostics == ("blocker:event_store_writer_inventory:refused",)

    report = GateReport(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256=digest,
        event_store_writer_failures=failures,
        diagnostics=diagnostics,
    )
    assert report.closed is False
    assert "event_store_writer_inventory_sha256:missing" in report.blockers
    assert "event_store_writer_failures:inventory-refused" in report.blockers


def test_stale_or_malformed_revision_cannot_produce_inventory_evidence(tmp_path) -> None:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    digest, failures, diagnostics = report_module._writer_inventory_evidence(
        tmp_path,
        "not-a-revision",
    )
    assert digest is None
    assert failures == ("inventory-refused",)
    assert diagnostics


def test_v2_rejects_unknown_fields_even_when_resigned() -> None:
    payload = _closed_report().to_dict()
    payload["invented_evidence"] = True
    _resign(payload)
    with pytest.raises(ValueError, match="shape"):
        GateReport.from_dict(payload)


def test_v2_rejects_nonboolean_security_claim_even_when_resigned() -> None:
    payload = _closed_report().to_dict()
    payload["security_boundary_claimed"] = "false"
    _resign(payload)
    with pytest.raises(ValueError, match="security_boundary_claimed"):
        GateReport.from_dict(payload)


def test_v2_rejects_string_where_array_is_required() -> None:
    payload = _closed_report().to_dict()
    payload["event_store_writer_failures"] = "none"
    _resign(payload)
    with pytest.raises(ValueError, match="JSON array"):
        GateReport.from_dict(payload)


def test_v2_rejects_inconsistent_closed_flag_after_valid_resign() -> None:
    report = GateReport(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=False,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256="c" * 64,
    )
    payload = report.to_dict()
    payload["closed"] = True
    _resign(payload)
    with pytest.raises(ValueError, match="closed flag"):
        GateReport.from_dict(payload)


def test_v2_rejects_inconsistent_blockers_after_valid_resign() -> None:
    report = GateReport(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=False,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256="c" * 64,
    )
    payload = report.to_dict()
    payload["blockers"] = []
    _resign(payload)
    with pytest.raises(ValueError, match="blockers"):
        GateReport.from_dict(payload)


def test_v2_rejects_noncanonical_duplicate_rows_after_valid_resign() -> None:
    report = GateReport(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=False,
        unguarded_entrypoints=("a",),
        event_store_writer_inventory_sha256="c" * 64,
    )
    payload = report.to_dict()
    payload["unguarded_entrypoints"] = ["a", "a"]
    _resign(payload)
    with pytest.raises(ValueError, match="noncanonical"):
        GateReport.from_dict(payload)


def test_v2_requires_report_digest() -> None:
    payload = _closed_report().to_dict()
    payload.pop("report_sha256")
    with pytest.raises(ValueError, match="shape"):
        GateReport.from_dict(payload)


def test_report_digest_tampering_cannot_remove_writer_failure() -> None:
    report = GateReport(
        gate=0,
        source_revision="a" * 40,
        registry_sha256="b" * 64,
        security_boundary_claimed=True,
        owner_approval_enforced=True,
        event_store_writer_inventory_sha256="c" * 64,
        event_store_writer_failures=(
            "daedalus/app.py:1:0:legacy_direct:daedalus.spine.SpineLedger",
        ),
    )
    payload = report.to_dict()
    payload["event_store_writer_failures"] = []
    with pytest.raises(ValueError, match="digest mismatch"):
        GateReport.from_dict(payload)


def test_parser_does_not_trust_serialized_closed_or_blocker_projection() -> None:
    source = Path(report_module.__file__).read_text(encoding="utf-8")
    assert "serialized_closed != report.closed" in source
    assert "serialized_blockers != report.blockers" in source
    assert "dict(payload) != report.to_dict()" in source
    assert "event_store_writer_inventory_sha256:missing" in source
