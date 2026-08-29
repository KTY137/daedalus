"""Admission v2 binds shared snapshot and authenticated ArtifactStore admission."""
from __future__ import annotations

import hashlib
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import daedalus.gates.repository_write_chain_admission_v2 as admission_v2
from daedalus.gates.report_v4 import GateReportV4
from daedalus.gates.repository_write_chain_admission import (
    RepositoryWriteChainAdmissionError,
)
from daedalus.gates.repository_write_chain_evidence import (
    RepositoryWriteChainArtifactEvidence,
)
from daedalus.gates.repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainSurface,
)
from daedalus.gates.repository_write_chain_snapshot_binding import (
    RepositoryWriteChainSnapshotBindingError,
)
from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_INPUT_SCHEMA,
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.gates.repository_write_non_runtime_sidecar import (
    RepositoryWriteNonRuntimeBindingSet,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
TREE = "b" * 40
NOW = datetime(2026, 8, 29, 14, 40, tzinfo=timezone.utc)
NOW_TEXT = NOW.isoformat(timespec="microseconds")
CONTENT = hashlib.sha256(b"chain-result-bytes").hexdigest()
LOCATOR = "6" * 64
ATTESTATION = "7" * 64
SNAPSHOT_RECEIPT = "8" * 64
ARTIFACT_ADMISSION = "9" * 64


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
        scan_input_sha256="c" * 64,
        files_scanned=3,
        base_inventory_digest="d" * 64,
        stdlib_delta_digest="e" * 64,
        surfaces=(surface,),
    )


def _chain(inventory: RepositoryWriteInventoryV2) -> RepositoryWriteChainResult:
    names = tuple(sorted(stage.value for stage in AuthenticationStage))
    surface = inventory.surfaces[0]
    retained = RepositoryWriteChainSurface(
        source_revision=REVISION,
        surface_sha256=hashlib.sha256(b"surface").hexdigest(),
        path=surface.path,
        line=surface.line,
        column=surface.column,
        origin=surface.origin,
        classification_verdict="cleared:central",
        candidate_blockers=(),
        applicable=names,
        stages=tuple((name, STAGE_VERDICT_VERIFIED) for name in names),
    )
    return RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        classification_digest="f" * 64,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=1,
        missing_surface_count=0,
        stage_digests=tuple(
            sorted(
                (stage.value, str(index) * 64)
                for index, stage in enumerate(AuthenticationStage, start=1)
            )
        ),
        surfaces=(retained,),
    )


def _report(
    inventory: RepositoryWriteInventoryV2,
    chain: RepositoryWriteChainResult,
) -> GateReportV4:
    return GateReportV4(
        gate=0,
        source_revision=REVISION,
        registry_sha256="1" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="2" * 64,
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
        repository_write_failures=(),
        repository_write_chain_result_schema=CHAIN_RESULT_SCHEMA,
        repository_write_chain_result_sha256=chain.digest,
    )


def _artifact(
    report: GateReportV4,
    chain: RepositoryWriteChainResult,
) -> RepositoryWriteChainArtifactEvidence:
    report_sha = report.to_dict()["report_sha256"]
    stage_set = canonical_sha(dict(chain.stage_digests))
    inputs = (
        report_sha,
        chain.digest,
        chain.inventory_digest,
        chain.classification_digest,
        stage_set,
        CONTENT,
    )
    return RepositoryWriteChainArtifactEvidence(
        artifact_id="repository-write-chain-result.1",
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v4_sha256=report_sha,
        chain_result_schema=CHAIN_RESULT_SCHEMA,
        chain_result_sha256=chain.digest,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_sha256=chain.inventory_digest,
        classification_sha256=chain.classification_digest,
        stage_digest_set_sha256=stage_set,
        inventory_surface_count=1,
        classified_surface_count=1,
        missing_surface_count=0,
        authenticated_surface_count=1,
        evidence_authenticated=True,
        artifact_content_sha256=CONTENT,
        locator=f"artifact-locator:sha256:{LOCATOR}",
        built_at="2026-08-29T14:30:00.000000+00:00",
        provenance=ContractProvenance(
            origin="gate0.repository-write-chain-artifact-evidence",
            source_revision=REVISION,
            created_at="2026-08-29T14:30:00.000000+00:00",
            input_digests=inputs,
        ),
    )


def _fixture():
    surface = _surface()
    inventory = _inventory(surface)
    chain = _chain(inventory)
    report = _report(inventory, chain)
    artifact = _artifact(report, chain)
    binding_set = RepositoryWriteNonRuntimeBindingSet(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        bindings=(),
    )
    document = {
        "schema": CLASSIFICATION_INPUT_SCHEMA,
        "source_revision": REVISION,
        "inventory_digest": inventory.digest,
        "classifications": [],
    }
    attestation = SimpleNamespace(digest=ATTESTATION)
    return artifact, report, inventory, document, binding_set, chain, attestation


def _snapshot(
    report: GateReportV4,
    inventory: RepositoryWriteInventoryV2,
    binding_set: RepositoryWriteNonRuntimeBindingSet,
    chain: RepositoryWriteChainResult,
    **overrides,
):
    values = dict(
        source_revision=REVISION,
        gate_report_v4_sha256=report.to_dict()["report_sha256"],
        inventory_sha256=inventory.digest,
        classification_sha256=chain.classification_digest,
        chain_result_sha256=chain.digest,
        non_runtime_binding_set_sha256=binding_set.digest,
        classified_surface_count=1,
        missing_surface_count=0,
        authenticated_surface_count=1,
        verified_at=NOW_TEXT,
        digest=SNAPSHOT_RECEIPT,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _artifact_admission(
    artifact: RepositoryWriteChainArtifactEvidence,
    report: GateReportV4,
    chain: RepositoryWriteChainResult,
    **overrides,
):
    values = dict(
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v4_sha256=report.to_dict()["report_sha256"],
        artifact_evidence_sha256=artifact.digest,
        artifact_content_sha256=artifact.artifact_content_sha256,
        chain_result_sha256=chain.digest,
        collector_attestation_sha256=ATTESTATION,
        evidence_authenticated=True,
        admitted_at=NOW_TEXT,
        artifact_locator_sha256=LOCATOR,
        digest=ARTIFACT_ADMISSION,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _call(fixture):
    artifact, report, inventory, document, binding_set, chain, attestation = fixture
    return admission_v2.admit_repository_write_chain_v2(
        artifact,
        report,
        inventory,
        document,
        binding_set,
        chain,
        object(),
        attestation,
        object(),
        primary_checkout="/primary-checkout",
        subjects={},
        non_runtime_collector_secrets={},
        collector_keyring={},
        expected_collector_id="collector.1",
        expected_collector_toolchain_sha256="3" * 64,
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW,
        snapshot_binding_id="shared-snapshot.1",
        resolution_id="chain-resolution.1",
        artifact_admission_id="artifact-admission.1",
        admission_id="chain-admission-v2.1",
    )


def test_public_v2_surface_accepts_neither_raw_bytes_nor_projected_classification() -> None:
    parameters = inspect.signature(admission_v2.admit_repository_write_chain_v2).parameters
    assert "artifact_bytes" not in parameters
    assert "raw" not in parameters
    assert "projection" not in parameters
    assert "classification_report" not in parameters
    assert "classification_input" in parameters


def test_v2_reconstructs_both_lower_receipts_and_cross_binds_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    artifact, report, inventory, _, binding_set, chain, _ = fixture
    seen: list[str] = []

    def snapshot_verify(*args, **kwargs):
        seen.append("snapshot")
        return _snapshot(report, inventory, binding_set, chain)

    def artifact_admit(*args, **kwargs):
        seen.append("artifact")
        return _artifact_admission(artifact, report, chain)

    monkeypatch.setattr(
        admission_v2,
        "verify_repository_write_chain_shared_snapshot",
        snapshot_verify,
    )
    monkeypatch.setattr(
        admission_v2,
        "admit_repository_write_chain",
        artifact_admit,
    )

    receipt = _call(fixture)

    assert seen == ["snapshot", "artifact"]
    assert receipt.shared_snapshot_sha256 == SNAPSHOT_RECEIPT
    assert receipt.artifact_admission_sha256 == ARTIFACT_ADMISSION
    assert receipt.inventory_sha256 == inventory.digest
    assert receipt.classification_sha256 == chain.classification_digest
    assert receipt.non_runtime_binding_set_sha256 == binding_set.digest
    assert receipt.artifact_locator_sha256 == LOCATOR
    assert receipt.evidence_authenticated is True
    assert admission_v2.RepositoryWriteChainAdmissionV2Receipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_snapshot_refusal_prevents_artifact_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    called = False

    def refuse(*args, **kwargs):
        raise RepositoryWriteChainSnapshotBindingError("foreign snapshot")

    def artifact_admit(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not run")

    monkeypatch.setattr(
        admission_v2,
        "verify_repository_write_chain_shared_snapshot",
        refuse,
    )
    monkeypatch.setattr(admission_v2, "admit_repository_write_chain", artifact_admit)

    with pytest.raises(
        admission_v2.RepositoryWriteChainAdmissionV2Error,
        match="shared inventory/classification snapshot refused",
    ):
        _call(fixture)
    assert called is False


def test_artifact_admission_refusal_prevents_v2_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    _, report, inventory, _, binding_set, chain, _ = fixture
    monkeypatch.setattr(
        admission_v2,
        "verify_repository_write_chain_shared_snapshot",
        lambda *args, **kwargs: _snapshot(report, inventory, binding_set, chain),
    )

    def refuse(*args, **kwargs):
        raise RepositoryWriteChainAdmissionError("collector refused")

    monkeypatch.setattr(admission_v2, "admit_repository_write_chain", refuse)
    with pytest.raises(
        admission_v2.RepositoryWriteChainAdmissionV2Error,
        match="authenticated artifact admission refused",
    ):
        _call(fixture)


def test_cross_wired_snapshot_classification_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    artifact, report, inventory, _, binding_set, chain, _ = fixture
    monkeypatch.setattr(
        admission_v2,
        "verify_repository_write_chain_shared_snapshot",
        lambda *args, **kwargs: _snapshot(
            report,
            inventory,
            binding_set,
            chain,
            classification_sha256="0" * 64,
        ),
    )
    monkeypatch.setattr(
        admission_v2,
        "admit_repository_write_chain",
        lambda *args, **kwargs: _artifact_admission(artifact, report, chain),
    )

    with pytest.raises(
        admission_v2.RepositoryWriteChainAdmissionV2Error,
        match="shared-snapshot receipt differs",
    ):
        _call(fixture)


def test_cross_wired_artifact_admission_authentication_state_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    artifact, report, inventory, _, binding_set, chain, _ = fixture
    monkeypatch.setattr(
        admission_v2,
        "verify_repository_write_chain_shared_snapshot",
        lambda *args, **kwargs: _snapshot(report, inventory, binding_set, chain),
    )
    monkeypatch.setattr(
        admission_v2,
        "admit_repository_write_chain",
        lambda *args, **kwargs: _artifact_admission(
            artifact,
            report,
            chain,
            evidence_authenticated=False,
        ),
    )

    with pytest.raises(
        admission_v2.RepositoryWriteChainAdmissionV2Error,
        match="artifact admission differs",
    ):
        _call(fixture)
