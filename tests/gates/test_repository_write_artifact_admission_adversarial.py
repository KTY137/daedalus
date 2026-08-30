# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

import daedalus.gates.repository_write_artifact_admission as admission_module
from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates.repository_write_artifact_admission import (
    RepositoryWriteArtifactAdmissionError,
    admit_repository_write_artifact,
)
from daedalus.gates.repository_write_artifact_cas import (
    RepositoryWriteArtifactCASRoot,
    artifact_relative_path,
    resolve_repository_write_artifact,
)
from daedalus.gates.repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationReceipt,
    verify_repository_write_artifact,
)
from daedalus.gates.repository_write_evidence import RepositoryWriteArtifactEvidence
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "1" * 40
TREE_REVISION = "2" * 40
BUILT_AT = "2026-08-05T00:00:00+00:00"
ADMITTED_AT = "2026-08-05T00:01:00+00:00"


def _subject(tmp_path: Path):
    inventory = RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="3" * 64,
        files_scanned=1,
        base_inventory_digest="4" * 64,
        stdlib_delta_digest="5" * 64,
        surfaces=(
            RepositoryWriteSurface(
                path="daedalus/example.py",
                line=7,
                column=4,
                origin="base_v1",
                kind="path-write",
                callee="Path.write_text",
                operation="write_text",
                blocking=True,
            ),
        ),
    )
    failures = tuple(
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        for surface in inventory.blockers
    )
    report = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256="6" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="7" * 64,
        repository_write_inventory_sha256=inventory.digest,
        repository_write_scan_input_sha256=inventory.scan_input_sha256,
        repository_write_files_scanned=inventory.files_scanned,
        repository_write_inventory_generation=2,
        repository_write_failures=failures,
    )
    raw = canonical_json(inventory.to_dict()).encode("ascii")
    content_sha256 = hashlib.sha256(raw).hexdigest()
    failure_set_sha256 = canonical_sha(list(failures))
    artifact = RepositoryWriteArtifactEvidence(
        artifact_id="artifact.repository-write-inventory",
        source_revision=REVISION,
        source_tree_revision=TREE_REVISION,
        gate_report_v3_sha256=report.to_dict()["report_sha256"],
        inventory_sha256=inventory.digest,
        scan_input_sha256=inventory.scan_input_sha256,
        files_scanned=inventory.files_scanned,
        inventory_generation=2,
        failure_set_sha256=failure_set_sha256,
        failure_count=len(failures),
        artifact_content_sha256=content_sha256,
        locator=f"artifact-locator:sha256:{content_sha256}",
        built_at=BUILT_AT,
        provenance=ContractProvenance(
            origin="test.repository-write-artifact",
            source_revision=REVISION,
            created_at=BUILT_AT,
            input_digests=(
                report.to_dict()["report_sha256"],
                inventory.digest,
                inventory.scan_input_sha256,
                failure_set_sha256,
                content_sha256,
            ),
        ),
    )
    cas = tmp_path / "cas"
    primary = tmp_path / "primary"
    cas.mkdir()
    primary.mkdir()
    root = RepositoryWriteArtifactCASRoot(
        path=str(cas.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=REVISION,
    )
    path = cas.joinpath(*artifact_relative_path(artifact.locator).split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return raw, report, artifact, root


def _call(artifact, report, root):
    return admit_repository_write_artifact(
        artifact,
        report,
        root,
        admission_id="admission.repository-write-artifact",
        resolution_id="resolution.repository-write-artifact",
        verification_id="verification.repository-write-artifact",
        admitted_at=ADMITTED_AT,
    )


def _dataclass_values(subject: object) -> dict[str, object]:
    return {
        field.name: getattr(subject, field.name)
        for field in dataclasses.fields(subject)
        if field.init
    }


def _replace_digest(
    receipt: RepositoryWriteArtifactVerificationReceipt,
    field_name: str,
    value: str,
) -> RepositoryWriteArtifactVerificationReceipt:
    old = getattr(receipt, field_name)
    provenance = dataclasses.replace(
        receipt.provenance,
        input_digests=tuple(
            value if digest == old else digest
            for digest in receipt.provenance.input_digests
        ),
    )
    return dataclasses.replace(receipt, provenance=provenance, **{field_name: value})


@pytest.mark.parametrize("subject", ["artifact", "report", "root"])
def test_exact_subject_subclasses_refuse(tmp_path: Path, subject: str) -> None:
    _, report, artifact, root = _subject(tmp_path)
    values = {"artifact": artifact, "report": report, "root": root}
    original = values[subject]
    substituted_type = type(f"{type(original).__name__}Subclass", (type(original),), {})
    values[subject] = substituted_type(**_dataclass_values(original))

    with pytest.raises(RepositoryWriteArtifactAdmissionError, match=f"{subject} must be exact"):
        _call(values["artifact"], values["report"], values["root"])


@pytest.mark.parametrize(
    "field_name,value,match",
    [
        ("source_revision", "a" * 40, "source revisions differ"),
        ("source_tree_revision", "b" * 40, "source-tree revisions differ"),
        ("artifact_evidence_sha256", "c" * 64, "artifact evidence differ"),
        ("artifact_content_sha256", "d" * 64, "content digests differ"),
        ("gate_report_v3_sha256", "e" * 64, "detached from GateReport-v3"),
    ],
)
def test_substituted_verifier_receipt_refuses_before_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    value: str,
    match: str,
) -> None:
    raw, report, artifact, root = _subject(tmp_path)
    resolved = resolve_repository_write_artifact(
        artifact,
        root,
        resolution_id="resolution.repository-write-artifact",
        resolved_at=ADMITTED_AT,
    )
    verification = verify_repository_write_artifact(
        artifact,
        report,
        raw,
        verification_id="verification.repository-write-artifact",
        verified_at=ADMITTED_AT,
    )
    if field_name in {
        "artifact_evidence_sha256",
        "artifact_content_sha256",
        "gate_report_v3_sha256",
    }:
        substituted = _replace_digest(verification, field_name, value)
    else:
        provenance = verification.provenance
        if field_name == "source_revision":
            provenance = dataclasses.replace(provenance, source_revision=value)
        substituted = dataclasses.replace(
            verification,
            provenance=provenance,
            **{field_name: value},
        )

    monkeypatch.setattr(
        admission_module,
        "resolve_repository_write_artifact",
        lambda *args, **kwargs: resolved,
    )
    monkeypatch.setattr(
        admission_module,
        "verify_repository_write_artifact",
        lambda *args, **kwargs: substituted,
    )

    with pytest.raises(RepositoryWriteArtifactAdmissionError, match=match):
        _call(artifact, report, root)


def test_resolution_and_verification_are_not_reordered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, report, artifact, root = _subject(tmp_path)
    order: list[str] = []
    original_resolver = admission_module.resolve_repository_write_artifact
    original_verifier = admission_module.verify_repository_write_artifact

    def resolving(*args, **kwargs):
        order.append("resolve")
        return original_resolver(*args, **kwargs)

    def verifying(*args, **kwargs):
        order.append("verify")
        return original_verifier(*args, **kwargs)

    monkeypatch.setattr(admission_module, "resolve_repository_write_artifact", resolving)
    monkeypatch.setattr(admission_module, "verify_repository_write_artifact", verifying)
    _call(artifact, report, root)
    assert order == ["resolve", "verify"]
