"""Collector replay attestation for repository-write verifier chains."""
from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.gates.repository_write_chain_collector_attestation as collector
from daedalus.gates.report_v4 import GateReportV4
from daedalus.gates.repository_write_chain_artifact_verifier import (
    RepositoryWriteChainArtifactVerificationReceipt,
    verify_repository_write_chain_artifact,
)
from daedalus.gates.repository_write_chain_evidence import (
    RepositoryWriteChainArtifactEvidence,
)
from daedalus.gates.repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainSurface,
)
from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteAuthenticationInputs,
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
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha

REVISION = "a" * 40
TREE = "b" * 40
SCAN = "c" * 64
TOOLCHAIN = "d" * 64
ISSUED = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
EXPIRES = ISSUED + timedelta(hours=1)
SECRET = b"collector-secret-material-at-least-32-bytes"


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
        base_inventory_digest="1" * 64,
        stdlib_delta_digest="2" * 64,
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


def _row(surface: RepositoryWriteSurface) -> SurfaceClassification:
    evidence = tuple(
        sorted(
            (
                _binding(
                    surface,
                    EvidenceKind.GUARD_CONTRACT,
                    "3",
                    guard_contract="containment.attempt",
                ),
                _binding(surface, EvidenceKind.EFFECT_LEASE_RECEIPT, "4"),
                _binding(
                    surface,
                    EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
                    "5",
                ),
                _binding(
                    surface,
                    EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
                    "6",
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
        notes="collector replay fixture",
    )


def _projection():
    surface = _surface()
    inventory = _inventory(surface)
    row = _row(surface)
    return (
        inventory,
        row,
        project_repository_write_classifications(inventory, (row,)),
    )


def _inputs() -> RepositoryWriteAuthenticationInputs:
    return RepositoryWriteAuthenticationInputs(
        blobs={},
        origin_attestation=object(),
        guard_manifest=object(),
        runtime_subjects={},
        runtime_trust_ledgers={},
        effect_subjects={},
        collector_keyring={},
        expected_collector_id="collector.1",
        guard_keyring={},
        expected_guard_authority_id="guard.1",
        current_revision=REVISION,
        now=object(),
        repository_root=Path("."),
    )


def _result(
    inventory: RepositoryWriteInventoryV2,
    row: SurfaceClassification,
    *,
    first_stage_digest: str = "7" * 64,
) -> RepositoryWriteChainResult:
    names = tuple(sorted(stage.value for stage in AuthenticationStage))
    stage_digests = tuple(
        (
            stage.value,
            first_stage_digest if index == 0 else str(index + 1) * 64,
        )
        for index, stage in enumerate(
            sorted(AuthenticationStage, key=lambda item: item.value)
        )
    )
    surface = RepositoryWriteChainSurface(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, row.surface),
        path=row.surface.path,
        line=row.surface.line,
        column=row.surface.column,
        origin=row.surface.origin,
        classification_verdict=surface_classification_verdict(row),
        candidate_blockers=row.candidate_blockers,
        applicable=names,
        stages=tuple((name, STAGE_VERDICT_VERIFIED) for name in names),
    )
    projection = project_repository_write_classifications(inventory, (row,))
    return RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        classification_digest=projection.digest,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=1,
        missing_surface_count=0,
        stage_digests=stage_digests,
        surfaces=(surface,),
    )


def _report(result: RepositoryWriteChainResult) -> GateReportV4:
    return GateReportV4(
        gate=0,
        source_revision=REVISION,
        registry_sha256="8" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="9" * 64,
        owner_approval_enforced=False,
        repository_write_inventory_sha256=result.inventory_digest,
        repository_write_scan_input_sha256=SCAN,
        repository_write_files_scanned=3,
        repository_write_inventory_generation=2,
        repository_write_inventory_schema=(
            "daedalus-gate0-repository-write-inventory/2"
        ),
        repository_write_scanner_error=0,
        repository_write_surfaces_total=result.inventory_surface_count,
        repository_write_classification_schema=CLASSIFICATION_SCHEMA,
        repository_write_surface_verdicts=("cleared:central:1",),
        repository_write_failures=(),
        repository_write_chain_result_schema=CHAIN_RESULT_SCHEMA,
        repository_write_chain_result_sha256=result.digest,
    )


def _raw(result: RepositoryWriteChainResult) -> bytes:
    return canonical_json(result.to_dict()).encode("ascii")


def _artifact(
    report: GateReportV4,
    result: RepositoryWriteChainResult,
    raw: bytes,
) -> RepositoryWriteChainArtifactEvidence:
    content = hashlib.sha256(raw).hexdigest()
    stage_set = canonical_sha(dict(result.stage_digests))
    inputs = (
        report.to_dict()["report_sha256"],
        result.digest,
        result.inventory_digest,
        result.classification_digest,
        stage_set,
        content,
    )
    return RepositoryWriteChainArtifactEvidence(
        artifact_id="repository-write-chain-result.1",
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v4_sha256=report.to_dict()["report_sha256"],
        chain_result_schema=CHAIN_RESULT_SCHEMA,
        chain_result_sha256=result.digest,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_sha256=result.inventory_digest,
        classification_sha256=result.classification_digest,
        stage_digest_set_sha256=stage_set,
        inventory_surface_count=result.inventory_surface_count,
        classified_surface_count=len(result.surfaces),
        missing_surface_count=result.missing_surface_count,
        authenticated_surface_count=result.authenticated_surface_count,
        evidence_authenticated=result.evidence_authenticated,
        artifact_content_sha256=content,
        locator=f"artifact-locator:sha256:{content}",
        built_at=ISSUED.isoformat(timespec="microseconds"),
        provenance=ContractProvenance(
            origin="gate0.repository-write-chain-artifact-evidence",
            source_revision=REVISION,
            created_at=ISSUED.isoformat(timespec="microseconds"),
            input_digests=inputs,
        ),
    )


def _verification(
    artifact: RepositoryWriteChainArtifactEvidence,
    report: GateReportV4,
    raw: bytes,
) -> RepositoryWriteChainArtifactVerificationReceipt:
    return verify_repository_write_chain_artifact(
        artifact,
        report,
        raw,
        verification_id="chain-verification.1",
        verified_at=ISSUED.isoformat(timespec="microseconds"),
    )


def _issue(
    monkeypatch: pytest.MonkeyPatch,
    replayed: RepositoryWriteChainResult,
    retained: RepositoryWriteChainResult,
):
    _, _, projection = _projection()
    report = _report(retained)
    raw = _raw(retained)
    artifact = _artifact(report, retained, raw)
    verification = _verification(artifact, report, raw)
    seen: dict[str, object] = {}

    def fake_builder(subject, **kwargs):
        seen["projection"] = subject
        seen.update(kwargs)
        return replayed

    monkeypatch.setattr(
        collector,
        "build_repository_write_chain_result",
        fake_builder,
    )
    attestation = collector.issue_repository_write_chain_collector_attestation(
        projection,
        inputs=_inputs(),
        retained_result=retained,
        artifact=artifact,
        verification=verification,
        report=report,
        artifact_bytes=raw,
        attestation_id="chain-replay.1",
        collector_id="collector.1",
        collector_key_id="key.1",
        collector_secret=SECRET,
        collector_toolchain_sha256=TOOLCHAIN,
        issued_at=ISSUED,
        expires_at=EXPIRES,
    )
    return (
        attestation,
        artifact,
        verification,
        report,
        raw,
        projection,
        seen,
    )


def test_issue_reruns_builder_and_verifier_accepts_exact_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, row, _ = _projection()
    result = _result(inventory, row)
    (
        attestation,
        artifact,
        verification,
        report,
        raw,
        projection,
        seen,
    ) = _issue(monkeypatch, result, result)

    assert seen["projection"] is projection
    assert type(seen["inputs"]) is RepositoryWriteAuthenticationInputs
    assert seen["non_runtime_bindings"] == ()
    assert seen["collector_secrets"] == {}
    assert attestation.evidence_authenticated is True
    assert collector.RepositoryWriteChainCollectorAttestation.from_dict(
        attestation.to_dict()
    ) == attestation

    collector.verify_repository_write_chain_collector_attestation(
        attestation,
        artifact,
        verification,
        result,
        report,
        raw,
        keyring={("collector.1", "key.1"): SECRET},
        expected_collector_id="collector.1",
        expected_collector_toolchain_sha256=TOOLCHAIN,
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=ISSUED + timedelta(minutes=1),
    )


def test_hand_authored_all_verified_result_is_refused_when_replay_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, row, projection = _projection()
    forged = _result(inventory, row)
    replayed = _result(inventory, row, first_stage_digest="8" * 64)
    report = _report(forged)
    raw = _raw(forged)
    artifact = _artifact(report, forged, raw)
    verification = _verification(artifact, report, raw)
    monkeypatch.setattr(
        collector,
        "build_repository_write_chain_result",
        lambda subject, **kwargs: replayed,
    )

    with pytest.raises(
        collector.RepositoryWriteChainCollectorBindingError,
        match="differs from collector replay",
    ):
        collector.issue_repository_write_chain_collector_attestation(
            projection,
            inputs=_inputs(),
            retained_result=forged,
            artifact=artifact,
            verification=verification,
            report=report,
            artifact_bytes=raw,
            attestation_id="chain-replay.1",
            collector_id="collector.1",
            collector_key_id="key.1",
            collector_secret=SECRET,
            collector_toolchain_sha256=TOOLCHAIN,
            issued_at=ISSUED,
            expires_at=EXPIRES,
        )


@pytest.mark.parametrize("mode", ("signature", "unknown-key"))
def test_signature_and_unknown_key_are_refused(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    inventory, row, _ = _projection()
    result = _result(inventory, row)
    (
        attestation,
        artifact,
        verification,
        report,
        raw,
        _,
        _,
    ) = _issue(monkeypatch, result, result)
    keyring = {("collector.1", "key.1"): SECRET}
    if mode == "signature":
        attestation = dataclasses.replace(
            attestation,
            signature_sha256="0" * 64,
        )
    else:
        keyring = {}

    with pytest.raises(collector.RepositoryWriteChainCollectorSignatureError):
        collector.verify_repository_write_chain_collector_attestation(
            attestation,
            artifact,
            verification,
            result,
            report,
            raw,
            keyring=keyring,
            expected_collector_id="collector.1",
            expected_collector_toolchain_sha256=TOOLCHAIN,
            current_revision=REVISION,
            current_tree_revision=TREE,
            now=ISSUED + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_collector_id", "collector.2"),
        ("expected_collector_toolchain_sha256", "0" * 64),
        ("current_revision", "0" * 40),
        ("current_tree_revision", "1" * 40),
    ),
)
def test_foreign_collector_toolchain_and_revisions_are_refused(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    inventory, row, _ = _projection()
    result = _result(inventory, row)
    (
        attestation,
        artifact,
        verification,
        report,
        raw,
        _,
        _,
    ) = _issue(monkeypatch, result, result)
    kwargs = {
        "expected_collector_id": "collector.1",
        "expected_collector_toolchain_sha256": TOOLCHAIN,
        "current_revision": REVISION,
        "current_tree_revision": TREE,
    }
    kwargs[field] = value
    with pytest.raises(
        collector.RepositoryWriteChainCollectorBindingError,
        match="binding mismatch|retained subject",
    ):
        collector.verify_repository_write_chain_collector_attestation(
            attestation,
            artifact,
            verification,
            result,
            report,
            raw,
            keyring={("collector.1", "key.1"): SECRET},
            now=ISSUED + timedelta(minutes=1),
            **kwargs,
        )


def test_expired_attestation_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, row, _ = _projection()
    result = _result(inventory, row)
    (
        attestation,
        artifact,
        verification,
        report,
        raw,
        _,
        _,
    ) = _issue(monkeypatch, result, result)
    with pytest.raises(
        collector.RepositoryWriteChainCollectorBindingError,
        match="expired",
    ):
        collector.verify_repository_write_chain_collector_attestation(
            attestation,
            artifact,
            verification,
            result,
            report,
            raw,
            keyring={("collector.1", "key.1"): SECRET},
            expected_collector_id="collector.1",
            expected_collector_toolchain_sha256=TOOLCHAIN,
            current_revision=REVISION,
            current_tree_revision=TREE,
            now=EXPIRES,
        )


def test_artifact_verification_substitution_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, row, _ = _projection()
    result = _result(inventory, row)
    (
        attestation,
        artifact,
        verification,
        report,
        raw,
        _,
        _,
    ) = _issue(monkeypatch, result, result)
    substituted = dataclasses.replace(
        verification,
        verification_id="chain-verification.2",
    )
    with pytest.raises(
        collector.RepositoryWriteChainCollectorBindingError,
        match="binding mismatch",
    ):
        collector.verify_repository_write_chain_collector_attestation(
            attestation,
            artifact,
            substituted,
            result,
            report,
            raw,
            keyring={("collector.1", "key.1"): SECRET},
            expected_collector_id="collector.1",
            expected_collector_toolchain_sha256=TOOLCHAIN,
            current_revision=REVISION,
            current_tree_revision=TREE,
            now=ISSUED + timedelta(minutes=1),
        )
