from __future__ import annotations

import dataclasses

import pytest

from daedalus.gates.report import GateReport
from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates.repository_write_evidence import (
    RepositoryWriteArtifactEvidence,
    RepositoryWriteArtifactEvidenceError,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


REVISION = "1" * 40
TREE = "2" * 40
BUILT_AT = "2026-08-04T20:00:00+00:00"
CONTENT = "f" * 64


def _report(**changes) -> GateReportV3:
    report = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256="a" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="b" * 64,
        repository_write_inventory_sha256="c" * 64,
        repository_write_scan_input_sha256="d" * 64,
        repository_write_files_scanned=7,
        repository_write_inventory_generation=2,
        repository_write_failures=("a.py:1:0:write", "z.py:2:0:write"),
    )
    return dataclasses.replace(report, **changes)


def _artifact(
    report: GateReportV3 | None = None,
    *,
    provenance_inputs: tuple[str, ...] | None = None,
    **changes,
) -> RepositoryWriteArtifactEvidence:
    bound = report or _report()
    values = {
        "artifact_id": "artifact.repository-write-inventory",
        "source_revision": bound.source_revision,
        "source_tree_revision": TREE,
        "gate_report_v3_sha256": bound.to_dict()["report_sha256"],
        "inventory_sha256": bound.repository_write_inventory_sha256,
        "scan_input_sha256": bound.repository_write_scan_input_sha256,
        "files_scanned": bound.repository_write_files_scanned,
        "inventory_generation": bound.repository_write_inventory_generation,
        "failure_set_sha256": canonical_sha(list(bound.repository_write_failures)),
        "failure_count": len(bound.repository_write_failures),
        "artifact_content_sha256": CONTENT,
        "locator": f"artifact-locator:sha256:{CONTENT}",
        "built_at": BUILT_AT,
    }
    values.update(changes)
    required = (
        values["gate_report_v3_sha256"],
        values["inventory_sha256"],
        values["scan_input_sha256"],
        values["failure_set_sha256"],
        values["artifact_content_sha256"],
    )
    values["provenance"] = ContractProvenance(
        origin="gate0.repository-write-artifact",
        source_revision=values["source_revision"],
        created_at=values["built_at"],
        input_digests=required if provenance_inputs is None else provenance_inputs,
    )
    return RepositoryWriteArtifactEvidence(**values)


def test_exact_artifact_round_trip_and_report_binding() -> None:
    report = _report()
    artifact = _artifact(report)
    assert artifact.report_binding_blockers(report) == ()
    assert RepositoryWriteArtifactEvidence.from_dict(artifact.to_dict()) == artifact
    assert len(artifact.digest) == 64
    assert artifact.locator.endswith(artifact.artifact_content_sha256)


@pytest.mark.parametrize(
    "report_change,expected",
    [
        (
            {"source_revision": "3" * 40},
            "repository-write-artifact:foreign-source-revision",
        ),
        (
            {"repository_write_inventory_sha256": "4" * 64},
            "repository-write-artifact:inventory-digest-mismatch",
        ),
        (
            {"repository_write_scan_input_sha256": "5" * 64},
            "repository-write-artifact:scan-input-digest-mismatch",
        ),
        (
            {"repository_write_files_scanned": 8},
            "repository-write-artifact:file-count-mismatch",
        ),
        (
            {"repository_write_inventory_generation": 0},
            "repository-write-artifact:generation-mismatch",
        ),
        (
            {"repository_write_failures": ("changed.py:1:0:write",)},
            "repository-write-artifact:failure-set-digest-mismatch",
        ),
    ],
)
def test_report_substitution_is_visible(report_change, expected: str) -> None:
    artifact = _artifact(_report())
    blockers = artifact.report_binding_blockers(_report(**report_change))
    assert "repository-write-artifact:foreign-gate-report" in blockers
    assert expected in blockers


def test_failure_count_substitution_is_visible() -> None:
    report = _report()
    artifact = _artifact(report, failure_count=99)
    assert artifact.report_binding_blockers(report) == (
        "repository-write-artifact:failure-count-mismatch",
    )


def test_locator_must_exactly_address_artifact_content() -> None:
    with pytest.raises(
        RepositoryWriteArtifactEvidenceError,
        match="locator digest contradicts",
    ):
        _artifact(locator=f"artifact-locator:sha256:{'e' * 64}")


def test_provenance_must_bind_every_referenced_digest() -> None:
    report = _report()
    required = (
        report.to_dict()["report_sha256"],
        report.repository_write_inventory_sha256,
        report.repository_write_scan_input_sha256,
        canonical_sha(list(report.repository_write_failures)),
    )
    with pytest.raises(
        RepositoryWriteArtifactEvidenceError,
        match="does not bind referenced input",
    ):
        _artifact(report, provenance_inputs=required)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("files_scanned", 0, "positive integer"),
        ("files_scanned", True, "non-negative integer"),
        ("inventory_generation", 1, "exactly 2"),
        ("inventory_generation", True, "non-negative integer"),
        ("failure_count", -1, "non-negative integer"),
        ("failure_count", False, "non-negative integer"),
    ],
)
def test_strict_integer_contracts_refuse(field: str, value, match: str) -> None:
    with pytest.raises(RepositoryWriteArtifactEvidenceError, match=match):
        _artifact(**{field: value})


def test_from_dict_requires_exact_contract_and_fields() -> None:
    payload = _artifact().to_dict()
    with pytest.raises(RepositoryWriteArtifactEvidenceError, match="payload is malformed"):
        RepositoryWriteArtifactEvidence.from_dict({**payload, "extra": "forbidden"})
    with pytest.raises(RepositoryWriteArtifactEvidenceError, match="payload is malformed"):
        RepositoryWriteArtifactEvidence.from_dict(
            {key: value for key, value in payload.items() if key != "inventory_sha256"}
        )
    with pytest.raises(RepositoryWriteArtifactEvidenceError, match="payload is malformed"):
        RepositoryWriteArtifactEvidence.from_dict(
            {**payload, "contract_type": "foreign-contract"}
        )


def test_binding_requires_exact_v3_report() -> None:
    artifact = _artifact()
    legacy = GateReport(
        gate=0,
        source_revision=REVISION,
        registry_sha256="a" * 64,
        # GateReport requires an explicit security-boundary claim; there is no
        # default, so a legacy report must still state it.
        security_boundary_claimed=False,
    )
    with pytest.raises(RepositoryWriteArtifactEvidenceError, match="exact GateReportV3"):
        artifact.report_binding_blockers(legacy)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("artifact_id", "artifact.repository-write-inventory-v2"),
        ("source_tree_revision", "6" * 40),
        ("artifact_content_sha256", "7" * 64),
        ("failure_count", 3),
    ],
)
def test_each_independent_artifact_dimension_changes_contract_digest(
    field: str,
    replacement,
) -> None:
    original = _artifact()
    if field == "artifact_content_sha256":
        changed = _artifact(
            artifact_content_sha256=replacement,
            locator=f"artifact-locator:sha256:{replacement}",
        )
    else:
        changed = _artifact(**{field: replacement})
    assert changed.digest != original.digest
