"""Strict evidence and byte verification for repository-write chain results."""
from __future__ import annotations

import hashlib
import json

import pytest

from daedalus.gates.report_v4 import GateReportV4
from daedalus.gates.repository_write_chain_artifact_verifier import (
    RepositoryWriteChainArtifactVerificationError,
    RepositoryWriteChainArtifactVerificationReceipt,
    verify_repository_write_chain_artifact,
)
from daedalus.gates.repository_write_chain_evidence import (
    RepositoryWriteChainArtifactEvidence,
    RepositoryWriteChainArtifactEvidenceError,
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
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha

REVISION = "a" * 40
TREE = "b" * 40
INVENTORY = "c" * 64
CLASSIFICATION = "d" * 64
BUILT_AT = "2026-08-25T08:30:00.000000+00:00"


def _stage_digests() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (stage.value, str(index) * 64)
            for index, stage in enumerate(AuthenticationStage, start=1)
        )
    )


def _result(*, empty: bool = False) -> RepositoryWriteChainResult:
    surfaces: tuple[RepositoryWriteChainSurface, ...] = ()
    if not empty:
        names = tuple(sorted(stage.value for stage in AuthenticationStage))
        surfaces = (
            RepositoryWriteChainSurface(
                source_revision=REVISION,
                surface_sha256="9" * 64,
                path="daedalus/example.py",
                line=7,
                column=4,
                origin="base_v1",
                classification_verdict="cleared:central",
                candidate_blockers=(),
                applicable=names,
                stages=tuple(
                    (name, STAGE_VERDICT_VERIFIED) for name in names
                ),
            ),
        )
    return RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest=INVENTORY,
        classification_digest=CLASSIFICATION,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=len(surfaces),
        missing_surface_count=0,
        stage_digests=_stage_digests(),
        surfaces=surfaces,
    )


def _report(
    result: RepositoryWriteChainResult,
    failures: tuple[str, ...] = (),
) -> GateReportV4:
    return GateReportV4(
        gate=0,
        source_revision=REVISION,
        registry_sha256="e" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="7" * 64,
        owner_approval_enforced=False,
        repository_write_inventory_sha256=INVENTORY,
        repository_write_scan_input_sha256="f" * 64,
        repository_write_files_scanned=1,
        repository_write_inventory_generation=2,
        repository_write_inventory_schema=(
            "daedalus-gate0-repository-write-inventory/2"
        ),
        repository_write_scanner_error=0,
        repository_write_surfaces_total=result.inventory_surface_count,
        repository_write_classification_schema=CLASSIFICATION_SCHEMA,
        repository_write_surface_verdicts=(
            () if not result.surfaces else ("cleared:central:1",)
        ),
        repository_write_failures=failures,
        repository_write_chain_result_schema=CHAIN_RESULT_SCHEMA,
        repository_write_chain_result_sha256=result.digest,
    )


def _raw(result: RepositoryWriteChainResult) -> bytes:
    return canonical_json(result.to_dict()).encode("ascii")


def _artifact(
    report: GateReportV4,
    result: RepositoryWriteChainResult,
    raw: bytes,
    **overrides: object,
) -> RepositoryWriteChainArtifactEvidence:
    content = hashlib.sha256(raw).hexdigest()
    stage_set = canonical_sha(dict(result.stage_digests))
    values: dict[str, object] = {
        "artifact_id": "repository-write-chain-result.1",
        "source_revision": REVISION,
        "source_tree_revision": TREE,
        "gate_report_v4_sha256": report.to_dict()["report_sha256"],
        "chain_result_schema": CHAIN_RESULT_SCHEMA,
        "chain_result_sha256": result.digest,
        "classification_schema": CLASSIFICATION_SCHEMA,
        "inventory_sha256": result.inventory_digest,
        "classification_sha256": result.classification_digest,
        "stage_digest_set_sha256": stage_set,
        "inventory_surface_count": result.inventory_surface_count,
        "classified_surface_count": len(result.surfaces),
        "missing_surface_count": result.missing_surface_count,
        "authenticated_surface_count": result.authenticated_surface_count,
        "evidence_authenticated": result.evidence_authenticated,
        "artifact_content_sha256": content,
        "locator": f"artifact-locator:sha256:{content}",
        "built_at": BUILT_AT,
    }
    values.update(overrides)
    values["provenance"] = ContractProvenance(
        origin="gate0.repository-write-chain-artifact-evidence",
        source_revision=REVISION,
        created_at=BUILT_AT,
        input_digests=tuple(
            str(values[name])
            for name in (
                "gate_report_v4_sha256",
                "chain_result_sha256",
                "inventory_sha256",
                "classification_sha256",
                "stage_digest_set_sha256",
                "artifact_content_sha256",
            )
        ),
    )
    return RepositoryWriteChainArtifactEvidence(**values)


def _verify(
    artifact: RepositoryWriteChainArtifactEvidence,
    report: GateReportV4,
    raw: bytes,
) -> RepositoryWriteChainArtifactVerificationReceipt:
    return verify_repository_write_chain_artifact(
        artifact,
        report,
        raw,
        verification_id="chain-verification.1",
        verified_at=BUILT_AT,
    )


def test_exact_evidence_and_bytes_emit_canonical_receipt() -> None:
    result = _result()
    report = _report(result)
    raw = _raw(result)
    artifact = _artifact(report, result, raw)
    receipt = _verify(artifact, report, raw)
    assert receipt.chain_result_sha256 == result.digest
    assert receipt.evidence_authenticated is True
    assert RepositoryWriteChainArtifactEvidence.from_dict(
        artifact.to_dict()
    ) == artifact
    assert RepositoryWriteChainArtifactVerificationReceipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_artifact_content_digest_substitution_is_refused() -> None:
    result = _result()
    report = _report(result)
    raw = _raw(result)
    forged = "0" * 64
    artifact = _artifact(
        report,
        result,
        raw,
        artifact_content_sha256=forged,
        locator=f"artifact-locator:sha256:{forged}",
    )
    with pytest.raises(
        RepositoryWriteChainArtifactVerificationError,
        match="byte digest",
    ):
        _verify(artifact, report, raw)


def test_semantically_equal_pretty_bytes_are_refused() -> None:
    result = _result()
    report = _report(result)
    raw = json.dumps(result.to_dict(), indent=2, sort_keys=True).encode()
    with pytest.raises(
        RepositoryWriteChainArtifactVerificationError,
        match="bytes are non-canonical",
    ):
        _verify(_artifact(report, result, raw), report, raw)


def test_foreign_chain_identity_is_refused() -> None:
    result = _result()
    report = _report(result)
    raw = _raw(result)
    artifact = _artifact(
        report,
        result,
        raw,
        chain_result_sha256="0" * 64,
    )
    with pytest.raises(
        RepositoryWriteChainArtifactVerificationError,
        match="chain-digest-mismatch",
    ):
        _verify(artifact, report, raw)


def test_derived_authentication_cannot_be_forged() -> None:
    result = _result()
    report = _report(result)
    raw = _raw(result)
    with pytest.raises(
        RepositoryWriteChainArtifactEvidenceError,
        match="not derived",
    ):
        _artifact(
            report,
            result,
            raw,
            authenticated_surface_count=0,
            evidence_authenticated=True,
        )
    artifact = _artifact(
        report,
        result,
        raw,
        authenticated_surface_count=0,
        evidence_authenticated=False,
    )
    with pytest.raises(
        RepositoryWriteChainArtifactVerificationError,
        match="authenticated_surface_count",
    ):
        _verify(artifact, report, raw)


def test_stage_digest_set_substitution_is_refused() -> None:
    result = _result()
    report = _report(result)
    raw = _raw(result)
    artifact = _artifact(
        report,
        result,
        raw,
        stage_digest_set_sha256="0" * 64,
    )
    with pytest.raises(
        RepositoryWriteChainArtifactVerificationError,
        match="stage_digest_set_sha256",
    ):
        _verify(artifact, report, raw)


@pytest.mark.parametrize(
    ("result", "failures"),
    (
        (_result(), ("classification:unexpected-failure",)),
        (_result(empty=True), ()),
    ),
)
def test_chain_authentication_and_report_failure_state_must_agree(
    result: RepositoryWriteChainResult,
    failures: tuple[str, ...],
) -> None:
    report = _report(result, failures)
    raw = _raw(result)
    with pytest.raises(
        RepositoryWriteChainArtifactVerificationError,
        match="failure state",
    ):
        _verify(_artifact(report, result, raw), report, raw)
