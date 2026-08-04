from __future__ import annotations

import dataclasses
import json

from daedalus.gates.repository_write_evidence import (
    RepositoryWriteArtifactEvidence,
)
from daedalus.schemas import ContractProvenance, KERNEL_CONTRACT_VERSION
from daedalus.spine.ledger import ROOT


SCHEMA = (
    ROOT
    / "configs"
    / "schemas"
    / "repository-write-artifact-evidence-v1.schema.json"
)


def test_schema_matches_exact_contract_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    contract_fields = {
        field.name for field in dataclasses.fields(RepositoryWriteArtifactEvidence)
    }
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == {
        "contract_type",
        "contract_version",
        *contract_fields,
    }
    assert payload["properties"]["contract_type"]["const"] == (
        RepositoryWriteArtifactEvidence.CONTRACT_TYPE
    )
    assert payload["properties"]["contract_version"]["const"] == (
        KERNEL_CONTRACT_VERSION
    )


def test_schema_encodes_exact_inventory_generation_and_integer_bounds() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["properties"]["files_scanned"] == {
        "type": "integer",
        "minimum": 1,
    }
    assert payload["properties"]["inventory_generation"] == {"const": 2}
    assert payload["properties"]["failure_count"] == {
        "type": "integer",
        "minimum": 0,
    }


def test_schema_provenance_shape_matches_canonical_contract() -> None:
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
    assert payload["properties"]["locator"]["pattern"] == (
        "^artifact-locator:sha256:[0-9a-f]{64}$"
    )
