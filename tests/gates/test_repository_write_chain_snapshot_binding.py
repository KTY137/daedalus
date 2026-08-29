"""One exact inventory/classification snapshot must feed report and chain."""
from __future__ import annotations

import dataclasses

import pytest

from daedalus.gates.report_v4 import GateReportV4
from daedalus.gates.repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainSurface,
)
from daedalus.gates.repository_write_chain_snapshot_binding import (
    RepositoryWriteChainSnapshotBindingError,
    RepositoryWriteChainSnapshotBindingReceipt,
    verify_repository_write_chain_shared_snapshot,
)
from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_INPUT_SCHEMA,
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    TargetDisposition,
    issue_non_runtime_conformity_binding,
    project_classification_input,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.gates.repository_write_non_runtime_sidecar import (
    RepositoryWriteNonRuntimeBindingSet,
    project_classification_input_with_non_runtime_sidecar,
)


REVISION = "a" * 40
SCAN = "b" * 64
VERIFIED_AT = "2026-08-29T14:30:00.000000+00:00"
ISSUED_AT = "2026-08-29T14:20:00.000000+00:00"
SECRET = b"snapshot-binding-secret-material-at-least-32-bytes"


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


def _evidence(
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


def _row_document(
    surface: RepositoryWriteSurface,
    *,
    runtime_receipt: bool,
) -> dict[str, object]:
    evidence = [
        _evidence(
            surface,
            EvidenceKind.GUARD_CONTRACT,
            "1",
            guard_contract="containment.attempt",
        ),
        _evidence(surface, EvidenceKind.EFFECT_LEASE_RECEIPT, "2"),
        _evidence(
            surface,
            EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            "3",
        ),
    ]
    if runtime_receipt:
        evidence.append(
            _evidence(surface, EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, "4")
        )
    evidence = sorted(evidence, key=EvidenceBinding.sort_key)
    return {
        "source_revision": REVISION,
        "surface": surface.to_dict(),
        "target": TargetDisposition.CHECKOUT_EXTERNAL.value,
        "guard": GuardDisposition.CENTRAL.value,
        "production_reachable": True,
        "guard_contracts": ["containment.attempt"],
        "evidence": [item.to_dict() for item in evidence],
        "notes": "shared snapshot fixture",
    }


def _document(
    inventory: RepositoryWriteInventoryV2,
    row: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": CLASSIFICATION_INPUT_SCHEMA,
        "source_revision": REVISION,
        "inventory_digest": inventory.digest,
        "classifications": [row],
    }


def _empty_binding_set(
    inventory: RepositoryWriteInventoryV2,
) -> RepositoryWriteNonRuntimeBindingSet:
    return RepositoryWriteNonRuntimeBindingSet(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        bindings=(),
    )


def _stage_digests() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (stage.value, str(index) * 64)
            for index, stage in enumerate(AuthenticationStage, start=1)
        )
    )


def _chain(
    inventory: RepositoryWriteInventoryV2,
    classification_digest: str,
    *,
    non_runtime_execution_id: str = "",
) -> RepositoryWriteChainResult:
    surface = inventory.surfaces[0]
    if non_runtime_execution_id:
        applicable = tuple(
            sorted(
                stage.value
                for stage in AuthenticationStage
                if stage is not AuthenticationStage.CONFORMITY
            )
        )
    else:
        applicable = tuple(sorted(stage.value for stage in AuthenticationStage))
    stages = tuple(
        (
            stage.value,
            (
                STAGE_VERDICT_NOT_APPLICABLE
                if non_runtime_execution_id
                and stage is AuthenticationStage.CONFORMITY
                else STAGE_VERDICT_VERIFIED
            ),
        )
        for stage in sorted(AuthenticationStage, key=lambda item: item.value)
    )
    retained = RepositoryWriteChainSurface(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        path=surface.path,
        line=surface.line,
        column=surface.column,
        origin=surface.origin,
        classification_verdict="cleared:central",
        candidate_blockers=(),
        applicable=applicable,
        stages=stages,
        not_applicable_binding=non_runtime_execution_id,
    )
    return RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        classification_digest=classification_digest,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=1,
        missing_surface_count=0,
        stage_digests=_stage_digests(),
        surfaces=(retained,),
    )


def _report(
    inventory: RepositoryWriteInventoryV2,
    chain: RepositoryWriteChainResult,
    *,
    failures: tuple[str, ...] = (),
    verdicts: tuple[str, ...] = ("cleared:central:1",),
) -> GateReportV4:
    return GateReportV4(
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
        repository_write_surfaces_total=len(inventory.surfaces),
        repository_write_classification_schema=CLASSIFICATION_SCHEMA,
        repository_write_surface_verdicts=verdicts,
        repository_write_failures=failures,
        repository_write_chain_result_schema=CHAIN_RESULT_SCHEMA,
        repository_write_chain_result_sha256=chain.digest,
    )


def _verify(
    report: GateReportV4,
    inventory: RepositoryWriteInventoryV2,
    document: dict[str, object],
    binding_set: RepositoryWriteNonRuntimeBindingSet,
    chain: RepositoryWriteChainResult,
    *,
    subjects: dict[str, object] | None = None,
):
    return verify_repository_write_chain_shared_snapshot(
        report,
        inventory,
        document,
        binding_set,
        chain,
        subjects={} if subjects is None else subjects,
        collector_secrets={"key.1": SECRET},
        binding_id="shared-snapshot.1",
        verified_at=VERIFIED_AT,
    )


def test_runtime_backed_report_and_chain_bind_to_one_exact_snapshot() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    projection = project_classification_input(inventory, document)
    chain = _chain(inventory, projection.digest)
    report = _report(inventory, chain)
    binding_set = _empty_binding_set(inventory)

    receipt = _verify(report, inventory, document, binding_set, chain)

    assert receipt.inventory_sha256 == inventory.digest
    assert receipt.classification_sha256 == projection.digest
    assert receipt.chain_result_sha256 == chain.digest
    assert receipt.non_runtime_binding_set_sha256 == binding_set.digest
    assert receipt.authenticated_surface_count == 1
    assert RepositoryWriteChainSnapshotBindingReceipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_report_inventory_substitution_is_refused_even_when_chain_is_valid() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    projection = project_classification_input(inventory, document)
    chain = _chain(inventory, projection.digest)
    report = dataclasses.replace(
        _report(inventory, chain),
        repository_write_inventory_sha256="f" * 64,
    )

    with pytest.raises(
        RepositoryWriteChainSnapshotBindingError,
        match="GateReport-v4 repository-write fields differ",
    ):
        _verify(report, inventory, document, _empty_binding_set(inventory), chain)


def test_report_verdict_or_failure_census_cannot_come_from_another_snapshot() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    projection = project_classification_input(inventory, document)
    chain = _chain(inventory, projection.digest)
    report = _report(
        inventory,
        chain,
        failures=("classification:foreign-failure",),
        verdicts=("blocked:foreign:1",),
    )

    with pytest.raises(
        RepositoryWriteChainSnapshotBindingError,
        match="repository-write fields differ",
    ):
        _verify(report, inventory, document, _empty_binding_set(inventory), chain)


def test_chain_classification_digest_substitution_is_refused() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    projection = project_classification_input(inventory, document)
    chain = dataclasses.replace(
        _chain(inventory, projection.digest),
        classification_digest="f" * 64,
    )
    report = _report(inventory, chain)

    with pytest.raises(
        RepositoryWriteChainSnapshotBindingError,
        match="chain result differs",
    ):
        _verify(report, inventory, document, _empty_binding_set(inventory), chain)


def test_signed_non_runtime_sidecar_reconstructs_same_applicability_across_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import daedalus.gates.repository_write_effect_lease as effect_lease

    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=False))
    binding = issue_non_runtime_conformity_binding(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        execution_id="execution.1",
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED_AT,
        secret=SECRET,
    )
    binding_set = RepositoryWriteNonRuntimeBindingSet(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        bindings=(binding,),
    )
    subject = object()
    seen: list[tuple[object, str]] = []

    def replay(retained, *, expected_execution_id: str):
        seen.append((retained, expected_execution_id))
        return object()

    monkeypatch.setattr(effect_lease, "replay_non_runtime_effect_subject", replay)
    projection = project_classification_input_with_non_runtime_sidecar(
        inventory,
        document,
        binding_set,
        subjects={binding.execution_id: subject},
        collector_secrets={binding.collector_key_id: SECRET},
    )
    chain = _chain(
        inventory,
        projection.digest,
        non_runtime_execution_id=binding.execution_id,
    )
    report = _report(inventory, chain)

    receipt = _verify(
        report,
        inventory,
        document,
        binding_set,
        chain,
        subjects={binding.execution_id: subject},
    )

    assert receipt.classification_sha256 == projection.digest
    assert receipt.non_runtime_binding_set_sha256 == binding_set.digest
    assert receipt.authenticated_surface_count == 1
    assert seen == [
        (subject, binding.execution_id),
        (subject, binding.execution_id),
    ]


def test_non_runtime_chain_binding_must_name_exact_sidecar_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import daedalus.gates.repository_write_effect_lease as effect_lease

    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=False))
    binding = issue_non_runtime_conformity_binding(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        execution_id="execution.1",
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED_AT,
        secret=SECRET,
    )
    binding_set = RepositoryWriteNonRuntimeBindingSet(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        bindings=(binding,),
    )
    subject = object()
    monkeypatch.setattr(
        effect_lease,
        "replay_non_runtime_effect_subject",
        lambda retained, *, expected_execution_id: object(),
    )
    projection = project_classification_input_with_non_runtime_sidecar(
        inventory,
        document,
        binding_set,
        subjects={binding.execution_id: subject},
        collector_secrets={binding.collector_key_id: SECRET},
    )
    chain = _chain(
        inventory,
        projection.digest,
        non_runtime_execution_id="execution.foreign",
    )
    report = _report(inventory, chain)

    with pytest.raises(
        RepositoryWriteChainSnapshotBindingError,
        match="chain result differs",
    ):
        _verify(
            report,
            inventory,
            document,
            binding_set,
            chain,
            subjects={binding.execution_id: subject},
        )


def test_sidecar_inventory_substitution_is_refused_before_report_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import daedalus.gates.repository_write_effect_lease as effect_lease

    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    projection = project_classification_input(inventory, document)
    chain = _chain(inventory, projection.digest)
    report = _report(inventory, chain)
    foreign = dataclasses.replace(
        _empty_binding_set(inventory),
        inventory_digest="f" * 64,
    )
    monkeypatch.setattr(
        effect_lease,
        "replay_non_runtime_effect_subject",
        lambda retained, *, expected_execution_id: object(),
    )

    with pytest.raises(
        RepositoryWriteChainSnapshotBindingError,
        match="classification reconstruction refused",
    ):
        _verify(report, inventory, document, foreign, chain)
