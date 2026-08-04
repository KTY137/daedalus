from __future__ import annotations

import dataclasses
import json

from daedalus.gates.repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationReceipt,
    _VERIFICATION_CHECKS,
)
from daedalus.schemas import ContractProvenance, KERNEL_CONTRACT_VERSION
from daedalus.spine.ledger import ROOT


SCHEMA = (
    ROOT
    / "configs"
    / "schemas"
    / "repository-write-artifact-verification-receipt-v1.schema.json"
)


def test_schema_matches_exact_receipt_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    receipt_fields = {
        field.name
        for field in dataclasses.fields(
            RepositoryWriteArtifactVerificationReceipt
        )
    }
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == {
        "contract_type",
        "contract_version",
        *receipt_fields,
    }
    assert payload["properties"]["contract_type"]["const"] == (
        RepositoryWriteArtifactVerificationReceipt.CONTRACT_TYPE
    )
    assert payload["properties"]["contract_version"]["const"] == (
        KERNEL_CONTRACT_VERSION
    )


def test_schema_encodes_exact_ordered_verification_checks() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    checks = payload["properties"]["checks"]
    assert tuple(item["const"] for item in checks["prefixItems"]) == (
        _VERIFICATION_CHECKS
    )
    assert checks["items"] is False
    assert checks["minItems"] == len(_VERIFICATION_CHECKS)
    assert checks["maxItems"] == len(_VERIFICATION_CHECKS)


def test_schema_provenance_matches_canonical_contract_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    provenance = payload["$defs"]["provenance"]
    assert provenance["additionalProperties"] is False
    assert set(provenance["required"]) == {
        field.name for field in dataclasses.fields(ContractProvenance)
    }
    assert provenance["properties"]["input_digests"]["uniqueItems"] is True
    assert payload["$defs"]["revision"]["pattern"] == (
        "^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
    )
    assert payload["$defs"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
