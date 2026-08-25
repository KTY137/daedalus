"""GateReport-v4 binds, rather than trusts, the retained verifier chain."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import daedalus.gates.report_v4 as report_v4
from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates.repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainSurface,
)
from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    SurfaceClassification,
    TargetDisposition,
    project_repository_write_classifications,
    surface_binding_sha256,
    surface_classification_verdict,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)


REVISION = "a" * 40
SCAN = "b" * 64


def _surface() -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path="daedalus/example.py",
        line=7,
        column=4,
        origin="base_v1",
        kind="open_write",
        callee="open",
        operation="mode='wb'",
        blocking=True,
    )


def _inventory(surface: RepositoryWriteSurface) -> RepositoryWriteInventoryV2:
    return RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256=SCAN,
        files_scanned=3,
        base_inventory_digest="c" * 64,
        stdlib_delta_digest="d" * 64,
        surfaces=(surface,),
    )


def _binding(
    surface: RepositoryWriteSurface,
    kind: EvidenceKind,
    digit: str,
    *,
    guard_contract: str = "",
) -> EvidenceBinding:
    return EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        sha256=digit * 64,
        locator=f"cas:sha256:{digit * 64}",
        guard_contract=guard_contract,
    )


def _classification(surface: RepositoryWriteSurface) -> SurfaceClassification:
    evidence = tuple(
        sorted(
            (
                _binding(
                    surface,
                    EvidenceKind.GUARD_CONTRACT,
                    "1",
                    guard_contract="containment.attempt",
                ),
                _binding(surface, EvidenceKind.EFFECT_LEASE_RECEIPT, "2"),
                _binding(surface, EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, "3"),
                _binding(
                    surface,
                    EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
                    "4",
                ),
            ),
            key=EvidenceBinding.sort_key,
        )
    )
    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=("containment.attempt",),
        evidence=evidence,
        notes="GateReport-v4 fixture",
    )


def _chain_surface(
    row: SurfaceClassification,
    *,
    path: str | None = None,
    applicable: tuple[str, ...] | None = None,
    candidate_blockers: tuple[str, ...] | None = None,
) -> RepositoryWriteChainSurface:
    applicable_rows = (
        tuple(sorted(stage.value for stage in AuthenticationStage))
        if applicable is None
        else applicable
    )
    verdicts = tuple(
        (
            stage.value,
            STAGE_VERDICT_VERIFIED
            if stage.value in applicable_rows
            else STAGE_VERDICT_NOT_APPLICABLE,
        )
        for stage in sorted(AuthenticationStage, key=lambda item: item.value)
    )
    blockers = row.candidate_blockers if candidate_blockers is None else candidate_blockers
    verdict = (
        surface_classification_verdict(row)
        if candidate_blockers is None
        else "blocked:" + "+".join(blockers)
    )
    conformity_applicable = AuthenticationStage.CONFORMITY.value in applicable_rows
    return RepositoryWriteChainSurface(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, row.surface),
        path=row.surface.path if path is None else path,
        line=row.surface.line,
        column=row.surface.column,
        origin=row.surface.origin,
        classification_verdict=verdict,
        candidate_blockers=tuple(blockers),
        applicable=applicable_rows,
        stages=verdicts,
        not_applicable_binding="" if conformity_applicable else "execution.1",
    )


def _chain(
    inventory: RepositoryWriteInventoryV2,
    row: SurfaceClassification,
    *,
    surface: RepositoryWriteChainSurface | None = None,
    classification_digest: str | None = None,
) -> RepositoryWriteChainResult:
    projection = project_repository_write_classifications(inventory, (row,))
    return RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        classification_digest=(
            projection.digest
            if classification_digest is None
            else classification_digest
        ),
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=1,
        missing_surface_count=0,
        stage_digests=tuple(
            sorted(
                (stage.value, str(index) * 64)
                for index, stage in enumerate(AuthenticationStage, start=1)
            )
        ),
        surfaces=(_chain_surface(row) if surface is None else surface,),
    )


def _base_report(
    inventory: RepositoryWriteInventoryV2,
    *,
    failures: tuple[str, ...],
) -> GateReportV3:
    return GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256="9" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="8" * 64,
        owner_approval_enforced=False,
        repository_write_inventory_sha256=inventory.digest,
        repository_write_scan_input_sha256=inventory.scan_input_sha256,
        repository_write_files_scanned=inventory.files_scanned,
        repository_write_inventory_generation=2,
        repository_write_inventory_schema=(
            "daedalus-gate0-repository-write-inventory/2"
        ),
        repository_write_scanner_error=0,
        repository_write_surfaces_total=1,
        repository_write_classification_schema=CLASSIFICATION_SCHEMA,
        repository_write_surface_verdicts=("cleared:central:1",),
        repository_write_failures=failures,
    )


def _v4_from_base(
    base: GateReportV3,
    chain: RepositoryWriteChainResult,
    *,
    failures: tuple[str, ...] = (),
) -> report_v4.GateReportV4:
    fields = {
        field.name: getattr(base, field.name)
        for field in dataclasses.fields(GateReportV3)
    }
    fields["repository_write_failures"] = failures
    return report_v4.GateReportV4(
        **fields,
        repository_write_chain_result_schema=CHAIN_RESULT_SCHEMA,
        repository_write_chain_result_sha256=chain.digest,
    )


def test_exact_chain_binding_and_gate_report_v4_round_trip() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    row = _classification(surface)
    projection = project_repository_write_classifications(inventory, (row,))
    chain = _chain(inventory, row)

    bound = report_v4.verify_repository_write_chain_result_binding(
        inventory,
        projection,
        chain,
    )
    assert bound[surface].authenticated is True

    report = _v4_from_base(_base_report(inventory, failures=()), chain)
    payload = report.to_dict()
    assert payload["schema"] == "daedalus-gate-report/6"
    assert payload["repository_write_chain_result_sha256"] == chain.digest
    assert report_v4.GateReportV4.from_dict(payload) == report


def test_binding_refuses_foreign_classification_applicability_and_identity() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    row = _classification(surface)
    projection = project_repository_write_classifications(inventory, (row,))

    with pytest.raises(report_v4.GateReportV4Error, match="classification"):
        report_v4.verify_repository_write_chain_result_binding(
            inventory,
            projection,
            _chain(inventory, row, classification_digest="f" * 64),
        )

    structural_only = tuple(
        sorted(
            stage.value
            for stage in (
                AuthenticationStage.MATERIALIZATION,
                AuthenticationStage.ORIGIN,
                AuthenticationStage.ANCHOR,
            )
        )
    )
    with pytest.raises(report_v4.GateReportV4Error, match="applicability"):
        report_v4.verify_repository_write_chain_result_binding(
            inventory,
            projection,
            _chain(
                inventory,
                row,
                surface=_chain_surface(row, applicable=structural_only),
            ),
        )

    with pytest.raises(report_v4.GateReportV4Error, match="identity"):
        report_v4.verify_repository_write_chain_result_binding(
            inventory,
            projection,
            _chain(
                inventory,
                row,
                surface=_chain_surface(row, path="daedalus/foreign.py"),
            ),
        )


def test_binding_refuses_candidate_blocker_substitution() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    row = _classification(surface)
    projection = project_repository_write_classifications(inventory, (row,))
    substituted = _chain_surface(
        row,
        candidate_blockers=("production-write-inventory_only",),
    )

    with pytest.raises(report_v4.GateReportV4Error, match="candidate blockers"):
        report_v4.verify_repository_write_chain_result_binding(
            inventory,
            projection,
            _chain(inventory, row, surface=substituted),
        )


def test_only_a_valid_binding_replaces_placeholder_authentication_failures() -> None:
    base = (
        "classification:evidence-unauthenticated:1",
        "classification:gate-report-binding-missing",
        "classification:surface-unauthenticated:daedalus/example.py:7:4:stages=anchor",
        "classification:unrelated-blocker",
    )
    valid = report_v4._ChainBindingSnapshot(
        CHAIN_RESULT_SCHEMA,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        (),
    )
    assert report_v4._bound_failures(base, valid) == (
        "classification:unrelated-blocker",
    )

    actual_failure = (
        "classification:surface-unauthenticated:daedalus/example.py:7:4:stages=lease",
        "classification:evidence-unauthenticated:1",
    )
    valid_but_unauthenticated = dataclasses.replace(
        valid,
        authentication_failures=actual_failure,
    )
    assert report_v4._bound_failures(base, valid_but_unauthenticated) == tuple(
        sorted({"classification:unrelated-blocker", *actual_failure})
    )

    refused = report_v4._ChainBindingSnapshot(
        None,
        None,
        None,
        None,
        (),
        "classification:chain-result-refused",
    )
    refused_rows = report_v4._bound_failures(base, refused)
    assert "classification:gate-report-binding-missing" in refused_rows
    assert "classification:chain-result-refused" in refused_rows


def test_builder_binds_a_stable_snapshot_without_claiming_gate_closure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    row = _classification(surface)
    chain = _chain(inventory, row)
    base = _base_report(
        inventory,
        failures=(
            "classification:evidence-unauthenticated:1",
            "classification:gate-report-binding-missing",
            "classification:surface-unauthenticated:daedalus/example.py:7:4:stages=lease",
        ),
    )
    snapshot = report_v4._ChainBindingSnapshot(
        CHAIN_RESULT_SCHEMA,
        chain.digest,
        inventory.digest,
        project_repository_write_classifications(inventory, (row,)).digest,
        (),
    )
    monkeypatch.setattr(report_v4, "build_gate0_report_v3", lambda root, **kwargs: base)
    monkeypatch.setattr(report_v4, "_resolve_chain_binding", lambda root, **kwargs: snapshot)

    report = report_v4.build_gate0_report_v4(
        tmp_path,
        source_revision=REVISION,
        repository_write_chain_result_input=tmp_path / "chain.json",
    )

    assert report.repository_write_failures == ()
    assert report.repository_write_chain_result_sha256 == chain.digest
    assert report.closed is False
    assert "security_boundary_claimed:false" in report.blockers
    assert "owner_approval_enforced:false" in report.blockers


def test_builder_refuses_chain_result_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    base = _base_report(inventory, failures=())
    first = report_v4._ChainBindingSnapshot(
        CHAIN_RESULT_SCHEMA,
        "1" * 64,
        inventory.digest,
        "2" * 64,
        (),
    )
    second = dataclasses.replace(first, digest="3" * 64)
    snapshots = iter((first, second))
    monkeypatch.setattr(report_v4, "build_gate0_report_v3", lambda root, **kwargs: base)
    monkeypatch.setattr(
        report_v4,
        "_resolve_chain_binding",
        lambda root, **kwargs: next(snapshots),
    )

    with pytest.raises(report_v4.GateReportV4Error, match="changed"):
        report_v4.build_gate0_report_v4(
            tmp_path,
            source_revision=REVISION,
            repository_write_chain_result_input=tmp_path / "chain.json",
        )
