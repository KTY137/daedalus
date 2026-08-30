# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path


SCHEMA = Path(
    "configs/schemas/provider-executable-structure-receipt.schema.json"
)


def test_structure_receipt_schema_is_strict_and_non_authorizing() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert document["type"] == "object"
    assert document["additionalProperties"] is False
    assert document["properties"]["schema"]["const"] == (
        "daedalus-provider-executable-structure-receipt/2"
    )
    assert (
        document["properties"]["target_authority_authenticated"]["const"]
        is True
    )
    assert (
        document["properties"]["targets_structurally_verified"]["const"]
        is True
    )
    assert (
        document["properties"]["repository_bytes_executed"]["const"]
        is False
    )
    assert (
        document["properties"]["provider_execution_allowed"]["const"]
        is False
    )
    assert (
        document["properties"][
            "source_revision_verified_against_git_head"
        ]["const"]
        is False
    )
    assert document["$defs"]["target"]["additionalProperties"] is False
    assert (
        document["$defs"]["target"]["properties"]["behavior_verified"]["const"]
        is False
    )
    assert (
        document["$defs"]["target"]["properties"]["executed"]["const"]
        is False
    )


def test_structure_receipt_schema_retains_complete_authority_chain() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))

    required_authority = {
        "execution_id",
        "idempotency_key",
        "target_contract_id",
        "lease_sha256",
        "target_authority_sha256",
        "invocation_authority_sha256",
        "invocation_contract_sha256",
        "identity_registry_sha256",
        "identity_descriptor_sha256",
        "adapter_artifact_sha256",
        "adapter_config_sha256",
    }
    assert required_authority <= set(document["required"])
    assert required_authority <= set(document["properties"])


def test_structure_receipt_schema_required_fields_match_properties() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert set(document["required"]) == set(document["properties"])
    target = document["$defs"]["target"]
    assert set(target["required"]) == set(target["properties"])
