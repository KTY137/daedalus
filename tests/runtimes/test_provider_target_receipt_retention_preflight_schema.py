from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


SCHEMA = Path(
    "configs/schemas/provider-target-receipt-retention-preflight.schema.json"
)


def _document() -> dict[str, object]:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


def test_preflight_schema_is_exact_and_non_authorizing() -> None:
    document = _document()

    assert document["type"] == "object"
    assert document["additionalProperties"] is False
    assert set(document["required"]) == set(document["properties"])
    properties = document["properties"]
    assert properties["schema"]["const"] == (
        "daedalus-provider-target-receipt-retention-preflight/1"
    )
    for field in (
        "repository_head_reverified",
        "repository_head_stable_across_inventory",
        "retention_inventory_rebuilt",
        "retention_authority_authenticated",
        "guard_decision_allowed",
    ):
        assert properties[field]["const"] is True
    for field in (
        "provider_execution_allowed",
        "persisted_effect_lease_verified",
        "retention_effect_started",
        "retention_write_performed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert properties[field]["const"] is False


def test_preflight_schema_binds_revision_inventory_digests_and_guard() -> None:
    document = _document()
    properties = document["properties"]

    assert properties["source_revision"]["pattern"] == "^[0-9a-f]{40}$"
    assert properties["retention_inventory_source_size"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 2097152,
    }
    assert properties["retention_inventory_surface_count"] == {
        "type": "integer",
        "const": 7,
    }
    for field in (
        "repository_head_receipt_sha256",
        "provider_target_receipt_sha256",
        "retention_inventory_sha256",
        "retention_inventory_source_sha256",
        "retention_authority_sha256",
        "retention_subject_sha256",
        "retention_execution_request_sha256",
        "retention_effect_lease_sha256",
    ):
        assert properties[field] == {"$ref": "#/$defs/sha256"}
    assert properties["guard_contract"]["const"] == (
        "provider.target_receipt_retention"
    )
    assert "authority_sha256" in properties["guard_evidence"]["pattern"]
    assert "subject_sha256" in properties["guard_evidence"]["pattern"]


def test_repository_path_definition_accepts_only_canonical_posix_paths() -> None:
    document = _document()
    pattern = document["$defs"]["repositoryPath"]["pattern"]

    assert re.fullmatch(pattern, "attempt/cas/receipts") is not None
    for value in (
        ".",
        "./attempt/cas",
        "attempt/./cas",
        "attempt//cas",
        "../attempt/cas",
        "attempt/../cas",
        "/attempt/cas",
        "C:/attempt/cas",
        "attempt\\cas",
    ):
        assert re.fullmatch(pattern, value) is None
