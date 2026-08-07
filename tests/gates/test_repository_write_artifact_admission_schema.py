from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.gates.repository_write_artifact_admission import (
    RepositoryWriteArtifactAdmissionError,
    RepositoryWriteArtifactAdmissionReceipt,
)
from daedalus.schemas import ContractProvenance


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "configs/schemas/repository-write-artifact-admission-receipt-v1.schema.json"
)
REVISION = "1" * 40
ADMITTED_AT = "2026-08-05T00:01:00+00:00"
DIGESTS = tuple(f"{value:x}" * 64 for value in range(1, 8))


def _receipt() -> RepositoryWriteArtifactAdmissionReceipt:
    provenance = ContractProvenance(
        origin="test.repository-write-artifact-admission",
        source_revision=REVISION,
        created_at=ADMITTED_AT,
        input_digests=DIGESTS,
    )
    return RepositoryWriteArtifactAdmissionReceipt(
        admission_id="admission.repository-write-artifact",
        source_revision=REVISION,
        source_tree_revision="2" * 40,
        gate_report_v3_sha256=DIGESTS[0],
        artifact_evidence_sha256=DIGESTS[1],
        artifact_content_sha256=DIGESTS[2],
        inventory_sha256=DIGESTS[3],
        cas_root_sha256=DIGESTS[4],
        resolution_receipt_sha256=DIGESTS[5],
        verification_receipt_sha256=DIGESTS[6],
        admitted_at=ADMITTED_AT,
        checks=(
            "cas-resolution",
            "cross-receipt-binding",
            "gate-report-v3-binding",
            "inventory-byte-verification",
        ),
        provenance=provenance,
    )


def test_schema_exactly_tracks_contract_fields_and_constants() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _receipt().to_dict()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(payload)
    assert set(schema["properties"]) == set(payload)
    assert schema["properties"]["contract_type"]["const"] == (
        RepositoryWriteArtifactAdmissionReceipt.CONTRACT_TYPE
    )
    assert schema["properties"]["contract_version"]["const"] == "1.0.0"
    checks = schema["properties"]["checks"]
    assert tuple(item["const"] for item in checks["prefixItems"]) == payload["checks"]
    assert checks["items"] is False
    assert checks["minItems"] == checks["maxItems"] == len(payload["checks"])


def test_contract_round_trip_rejects_extra_or_missing_fields() -> None:
    payload = _receipt().to_dict()
    extra = dict(payload, release_authorized=True)
    with pytest.raises(RepositoryWriteArtifactAdmissionError):
        RepositoryWriteArtifactAdmissionReceipt.from_dict(extra)

    missing = dict(payload)
    missing.pop("verification_receipt_sha256")
    with pytest.raises(RepositoryWriteArtifactAdmissionError):
        RepositoryWriteArtifactAdmissionReceipt.from_dict(missing)


def test_schema_digest_and_revision_patterns_remain_fail_closed() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$defs"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert schema["$defs"]["revision"]["pattern"] == (
        "^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
    )
    for field in (
        "gate_report_v3_sha256",
        "artifact_evidence_sha256",
        "artifact_content_sha256",
        "inventory_sha256",
        "cas_root_sha256",
        "resolution_receipt_sha256",
        "verification_receipt_sha256",
    ):
        assert schema["properties"][field] == {"$ref": "#/$defs/sha256"}
