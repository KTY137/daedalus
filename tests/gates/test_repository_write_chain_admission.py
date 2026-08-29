"""Atomic admission of store-resolved repository-write chain evidence."""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.gates.repository_write_chain_admission as admission
from daedalus.gates.report_v4 import GateReportV4
from daedalus.gates.repository_write_chain_artifact_verifier import (
    verify_repository_write_chain_artifact,
)
from daedalus.gates.repository_write_chain_collector_attestation import (
    RepositoryWriteChainCollectorAttestation,
    RepositoryWriteChainCollectorBindingError,
)
from daedalus.gates.repository_write_chain_evidence import (
    RepositoryWriteChainArtifactEvidence,
)
from daedalus.gates.repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainSurface,
)
from daedalus.gates.repository_write_chain_store_resolution import (
    CHAIN_RESULT_MEDIA_TYPE,
    CHAIN_RESULT_STORE_METADATA,
    CHAIN_RESULT_STORE_ORIGIN,
)
from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.storage import ArtifactStore


REVISION = "a" * 40
TREE = "b" * 40
INVENTORY = "c" * 64
CLASSIFICATION = "d" * 64
TOOLCHAIN = "e" * 64
BUILT = datetime(2026, 8, 29, 14, 10, tzinfo=timezone.utc)
VERIFIED = BUILT + timedelta(seconds=10)
ISSUED = BUILT + timedelta(seconds=20)
NOW = BUILT + timedelta(seconds=30)
SECRET = b"collector-secret-material-at-least-32-bytes"


def _stage_digests() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (stage.value, str(index) * 64)
            for index, stage in enumerate(AuthenticationStage, start=1)
        )
    )


def _result() -> RepositoryWriteChainResult:
    names = tuple(sorted(stage.value for stage in AuthenticationStage))
    surface = RepositoryWriteChainSurface(
        source_revision=REVISION,
        surface_sha256="9" * 64,
        path="daedalus/example.py",
        line=7,
        column=4,
        origin="base_v1",
        classification_verdict="cleared:central",
        candidate_blockers=(),
        applicable=names,
        stages=tuple((name, STAGE_VERDICT_VERIFIED) for name in names),
    )
    return RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest=INVENTORY,
        classification_digest=CLASSIFICATION,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=1,
        missing_surface_count=0,
        stage_digests=_stage_digests(),
        surfaces=(surface,),
    )


def _report(result: RepositoryWriteChainResult) -> GateReportV4:
    return GateReportV4(
        gate=0,
        source_revision=REVISION,
        registry_sha256="f" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="7" * 64,
        owner_approval_enforced=False,
        repository_write_inventory_sha256=INVENTORY,
        repository_write_scan_input_sha256="8" * 64,
        repository_write_files_scanned=1,
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
        repository_write_chain_result_sha256=result.digest,
    )


def _time(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _fixture(tmp_path: Path):
    result = _result()
    report = _report(result)
    raw = canonical_json(result.to_dict()).encode("ascii")
    content = __import__("hashlib").sha256(raw).hexdigest()
    stage_set = canonical_sha(dict(result.stage_digests))
    report_sha = report.to_dict()["report_sha256"]
    artifact_inputs = (
        report_sha,
        result.digest,
        result.inventory_digest,
        result.classification_digest,
        stage_set,
        content,
    )

    store = ArtifactStore(tmp_path / "cas", min_free_gib=0.0)
    locator = store.put_bytes(
        raw,
        expected_sha256=content,
        media_type=CHAIN_RESULT_MEDIA_TYPE,
        metadata=CHAIN_RESULT_STORE_METADATA,
        provenance={
            "origin": CHAIN_RESULT_STORE_ORIGIN,
            "source_revision": REVISION,
            "created_at": _time(BUILT),
            "input_digests": sorted(set(artifact_inputs)),
            "trace_id": "repository-write-chain-result.1",
        },
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    artifact = RepositoryWriteChainArtifactEvidence(
        artifact_id="repository-write-chain-result.1",
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v4_sha256=report_sha,
        chain_result_schema=CHAIN_RESULT_SCHEMA,
        chain_result_sha256=result.digest,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_sha256=result.inventory_digest,
        classification_sha256=result.classification_digest,
        stage_digest_set_sha256=stage_set,
        inventory_surface_count=1,
        classified_surface_count=1,
        missing_surface_count=0,
        authenticated_surface_count=1,
        evidence_authenticated=True,
        artifact_content_sha256=content,
        locator=locator.locator_uri,
        built_at=_time(BUILT),
        provenance=ContractProvenance(
            origin="gate0.repository-write-chain-artifact-evidence",
            source_revision=REVISION,
            created_at=_time(BUILT),
            input_digests=artifact_inputs,
        ),
    )
    verification = verify_repository_write_chain_artifact(
        artifact,
        report,
        raw,
        verification_id="chain-verification.1",
        verified_at=_time(VERIFIED),
    )
    attestation_inputs = tuple(
        sorted(
            {
                report_sha,
                artifact.digest,
                verification.digest,
                content,
                result.digest,
                result.inventory_digest,
                result.classification_digest,
                stage_set,
                TOOLCHAIN,
            }
        )
    )
    attestation = RepositoryWriteChainCollectorAttestation(
        attestation_id="chain-replay.1",
        collector_id="collector.1",
        collector_key_id="key.1",
        builder_id="gate0.repository-write-chain-result-builder/1",
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v4_sha256=report_sha,
        artifact_evidence_sha256=artifact.digest,
        artifact_verification_sha256=verification.digest,
        artifact_content_sha256=content,
        chain_result_sha256=result.digest,
        inventory_sha256=result.inventory_digest,
        classification_sha256=result.classification_digest,
        stage_digest_set_sha256=stage_set,
        collector_toolchain_sha256=TOOLCHAIN,
        inventory_surface_count=1,
        classified_surface_count=1,
        missing_surface_count=0,
        authenticated_surface_count=1,
        evidence_authenticated=True,
        issued_at=_time(ISSUED),
        expires_at=_time(ISSUED + timedelta(hours=1)),
        signature_sha256="6" * 64,
        provenance=ContractProvenance(
            origin="gate0.repository-write-chain-collector-replay",
            source_revision=REVISION,
            created_at=_time(ISSUED),
            input_digests=attestation_inputs,
            trace_id="chain-replay.1",
        ),
    )
    return result, report, raw, artifact, verification, attestation, store, checkout, locator


def _admit(
    fixture,
):
    result, report, _, artifact, verification, attestation, store, checkout, _ = fixture
    return admission.admit_repository_write_chain(
        artifact,
        report,
        result,
        verification,
        attestation,
        store,
        primary_checkout=str(checkout),
        keyring={("collector.1", "key.1"): SECRET},
        expected_collector_id="collector.1",
        expected_collector_toolchain_sha256=TOOLCHAIN,
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW,
        resolution_id="chain-store-resolution.1",
        admission_id="chain-admission.1",
    )


def test_public_admission_surface_has_no_raw_artifact_bytes_parameter() -> None:
    parameters = inspect.signature(admission.admit_repository_write_chain).parameters
    assert "artifact_bytes" not in parameters
    assert "raw" not in parameters


def test_admission_resolves_bytes_replays_verifier_and_calls_collector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    seen: dict[str, object] = {}

    def fake_collector_verify(
        attestation,
        artifact,
        verification,
        retained_result,
        report,
        artifact_bytes,
        **kwargs,
    ) -> None:
        seen["attestation"] = attestation
        seen["artifact"] = artifact
        seen["verification"] = verification
        seen["retained_result"] = retained_result
        seen["report"] = report
        seen["artifact_bytes"] = artifact_bytes
        seen.update(kwargs)

    monkeypatch.setattr(
        admission,
        "verify_repository_write_chain_collector_attestation",
        fake_collector_verify,
    )
    receipt = _admit(fixture)
    result, report, raw, artifact, verification, attestation, _, _, locator = fixture

    assert seen["artifact_bytes"] == raw
    assert seen["artifact"] is artifact
    assert seen["verification"] is verification
    assert seen["retained_result"] is result
    assert seen["report"] is report
    assert receipt.artifact_locator_sha256 == locator.locator_sha256
    assert receipt.artifact_verification_sha256 == verification.digest
    assert receipt.collector_attestation_sha256 == attestation.digest
    assert receipt.evidence_authenticated is True
    assert admission.RepositoryWriteChainAdmissionReceipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_attestation_over_different_verification_receipt_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    result, report, raw, artifact, _, attestation, store, checkout, _ = fixture
    alternate = verify_repository_write_chain_artifact(
        artifact,
        report,
        raw,
        verification_id="chain-verification.alternate",
        verified_at=_time(VERIFIED),
    )
    monkeypatch.setattr(
        admission,
        "verify_repository_write_chain_collector_attestation",
        lambda *args, **kwargs: None,
    )
    with pytest.raises(
        admission.RepositoryWriteChainAdmissionError,
        match="attestation differs",
    ):
        admission.admit_repository_write_chain(
            artifact,
            report,
            result,
            alternate,
            attestation,
            store,
            primary_checkout=str(checkout),
            keyring={("collector.1", "key.1"): SECRET},
            expected_collector_id="collector.1",
            expected_collector_toolchain_sha256=TOOLCHAIN,
            current_revision=REVISION,
            current_tree_revision=TREE,
            now=NOW,
            resolution_id="chain-store-resolution.1",
            admission_id="chain-admission.1",
        )


def test_store_corruption_prevents_collector_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    *_, locator = fixture
    called = False

    def fake_collector_verify(*args, **kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        admission,
        "verify_repository_write_chain_collector_attestation",
        fake_collector_verify,
    )
    locator.blob_path.write_bytes(b"tampered")
    with pytest.raises(
        admission.RepositoryWriteChainAdmissionError,
        match="ArtifactStore resolution refused",
    ):
        _admit(fixture)
    assert called is False


def test_collector_refusal_prevents_admission_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)

    def refuse(*args, **kwargs) -> None:
        raise RepositoryWriteChainCollectorBindingError("expired")

    monkeypatch.setattr(
        admission,
        "verify_repository_write_chain_collector_attestation",
        refuse,
    )
    with pytest.raises(
        admission.RepositoryWriteChainAdmissionError,
        match="collector replay attestation refused",
    ):
        _admit(fixture)


def test_resolution_and_verification_subjects_cannot_be_cross_wired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    result, report, raw, artifact, _, attestation, store, checkout, _ = fixture
    foreign_artifact = RepositoryWriteChainArtifactEvidence.from_dict(
        artifact.to_dict()
    )
    foreign_verification = verify_repository_write_chain_artifact(
        foreign_artifact,
        report,
        raw,
        verification_id="chain-verification.foreign",
        verified_at=_time(VERIFIED),
    )
    monkeypatch.setattr(
        admission,
        "verify_repository_write_chain_collector_attestation",
        lambda *args, **kwargs: None,
    )
    with pytest.raises(
        admission.RepositoryWriteChainAdmissionError,
        match="attestation differs",
    ):
        admission.admit_repository_write_chain(
            artifact,
            report,
            result,
            foreign_verification,
            attestation,
            store,
            primary_checkout=str(checkout),
            keyring={("collector.1", "key.1"): SECRET},
            expected_collector_id="collector.1",
            expected_collector_toolchain_sha256=TOOLCHAIN,
            current_revision=REVISION,
            current_tree_revision=TREE,
            now=NOW,
            resolution_id="chain-store-resolution.1",
            admission_id="chain-admission.1",
        )
