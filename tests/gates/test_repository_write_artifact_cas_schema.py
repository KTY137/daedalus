from __future__ import annotations

import dataclasses
import json

from daedalus.gates.repository_write_artifact_cas import (
    RepositoryWriteArtifactResolutionReceipt,
    _MAX_ARTIFACT_BYTES,
    _RESOLUTION_CHECKS,
)
from daedalus.schemas import ContractProvenance, KERNEL_CONTRACT_VERSION
from daedalus.spine.ledger import ROOT


SCHEMA = (
    ROOT
    / "configs"
    / "schemas"
    / "repository-write-artifact-resolution-receipt-v1.schema.json"
)


def test_schema_matches_exact_receipt_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    receipt_fields = {
        field.name
        for field in dataclasses.fields(RepositoryWriteArtifactResolutionReceipt)
    }
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == {
        "contract_type",
        "contract_version",
        *receipt_fields,
    }
    assert payload["properties"]["contract_type"]["const"] == (
        RepositoryWriteArtifactResolutionReceipt.CONTRACT_TYPE
    )
    assert payload["properties"]["contract_version"]["const"] == (
        KERNEL_CONTRACT_VERSION
    )


def test_schema_encodes_exact_ordered_resolution_checks() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    checks = payload["properties"]["checks"]
    assert tuple(item["const"] for item in checks["prefixItems"]) == (
        _RESOLUTION_CHECKS
    )
    assert checks["items"] is False
    assert checks["minItems"] == len(_RESOLUTION_CHECKS)
    assert checks["maxItems"] == len(_RESOLUTION_CHECKS)


def test_schema_binds_locator_path_and_byte_ceiling() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["properties"]["locator"]["pattern"] == (
        "^artifact-locator:sha256:[0-9a-f]{64}$"
    )
    assert payload["properties"]["relative_path"]["pattern"] == (
        "^sha256/[0-9a-f]{2}/[0-9a-f]{62}$"
    )
    assert payload["properties"]["file_size"]["minimum"] == 1
    assert payload["properties"]["file_size"]["maximum"] == _MAX_ARTIFACT_BYTES


def test_schema_provenance_matches_canonical_contract_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    provenance = payload["$defs"]["provenance"]
    assert provenance["additionalProperties"] is False
    assert set(provenance["required"]) == {
        field.name for field in dataclasses.fields(ContractProvenance)
    }
    assert provenance["properties"]["input_digests"]["uniqueItems"] is True
