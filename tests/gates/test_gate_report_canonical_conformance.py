from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.gates import report as report_module
from daedalus.gates import report_v3 as report_v3_module
from daedalus.gates.report import GateReport, build_gate0_report
from daedalus.spine.effect_boundary import (
    ConformanceFinding,
    ConformanceReport,
    REGISTRY_BY_ID,
    Wiring,
)


REVISION = "a" * 40
REGISTRY_DIGEST = "b" * 64
WRITER_DIGEST = "c" * 64
SENTINEL = f"canonical-effect-boundary:gate0-open:{REGISTRY_DIGEST}"


def _conformance(
    wiring: Wiring = Wiring.CENTRAL,
    *,
    findings: tuple[ConformanceFinding, ...] = (),
) -> ConformanceReport:
    rows = tuple(REGISTRY_BY_ID.values())
    assert rows
    matrix = (dataclasses.replace(rows[0], wiring=wiring),) + tuple(
        dataclasses.replace(row, wiring=Wiring.CENTRAL) for row in rows[1:]
    )
    return ConformanceReport(
        registry_sha256=REGISTRY_DIGEST,
        discoveries=(),
        findings=findings,
        matrix=matrix,
    )


def _build(
    monkeypatch: pytest.MonkeyPatch,
    conformance: ConformanceReport,
) -> GateReport:
    monkeypatch.setattr(report_module, "check_conformance", lambda root: conformance)
    monkeypatch.setattr(
        report_module,
        "bind_runtime_conformance_receipts",
        lambda *args, **kwargs: SimpleNamespace(failures=(), diagnostics=()),
    )
    monkeypatch.setattr(
        report_module,
        "bind_fault_matrix_evidence",
        lambda *args, **kwargs: SimpleNamespace(failures=(), diagnostics=()),
    )
    monkeypatch.setattr(
        report_module,
        "_writer_inventory_evidence",
        lambda *args, **kwargs: (WRITER_DIGEST, (), ()),
    )
    return build_gate0_report(
        Path("."),
        source_revision=REVISION,
        security_boundary_claimed=True,
    )


@pytest.mark.parametrize(
    "wiring",
    (
        Wiring.LOCAL_GUARDS,
        Wiring.INVENTORY_ONLY,
        Wiring.UNGUARDED,
        Wiring.ABSENT,
    ),
)
def test_every_noncentral_wiring_adds_registry_bound_canonical_blocker(
    monkeypatch: pytest.MonkeyPatch,
    wiring: Wiring,
) -> None:
    report = _build(monkeypatch, _conformance(wiring))

    assert SENTINEL in report.runtime_conformance_failures
    assert f"runtime_conformance_failures:{SENTINEL}" in report.blockers
    assert report.closed is False


def test_future_structural_blocker_cannot_fall_out_of_gate_report_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finding = ConformanceFinding(
        code="future.structural_blocker",
        severity="blocker",
        subject="synthetic.future.entrypoint",
        detail="an unenumerated canonical structural failure",
    )
    report = _build(monkeypatch, _conformance(findings=(finding,)))

    assert SENTINEL in report.runtime_conformance_failures
    assert report.closed is False


def test_all_central_structurally_conformant_control_has_no_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _build(monkeypatch, _conformance())

    assert SENTINEL not in report.runtime_conformance_failures
    assert report.closed is True


def test_v3_builder_cannot_drop_the_base_conformance_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256=REGISTRY_DIGEST,
        security_boundary_claimed=True,
        runtime_conformance_failures=(SENTINEL,),
        event_store_writer_inventory_sha256=WRITER_DIGEST,
        owner_approval_enforced=True,
    )
    monkeypatch.setattr(
        report_v3_module,
        "_build_base_report",
        lambda *args, **kwargs: base,
    )
    monkeypatch.setattr(
        report_v3_module,
        "_repository_write_evidence",
        lambda *args, **kwargs: (
            "d" * 64,
            "e" * 64,
            1,
            2,
            (),
            (),
            "daedalus-gate0-repository-write-inventory/2",
            0,
            1,
            "daedalus-gate0-repository-write-classification/2",
            ("cleared:central:1",),
        ),
    )

    report = report_v3_module.build_gate0_report_v3(
        Path("."),
        source_revision=REVISION,
    )

    assert SENTINEL in report.runtime_conformance_failures
    assert f"runtime_conformance_failures:{SENTINEL}" in report.blockers
    assert report.closed is False
