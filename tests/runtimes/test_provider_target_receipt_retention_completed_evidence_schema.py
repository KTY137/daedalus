# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


SCHEMA = Path(
    "configs/schemas/provider-target-receipt-retention-completed-evidence.schema.json"
)


def _document() -> dict[str, object]:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


def _payload() -> dict[str, object]:
    return {
        "schema": (
            "daedalus-provider-target-receipt-retention-completed-evidence/1"
        ),
        "source_revision": "1" * 40,
        "admission_sha256": "2" * 64,
        "recovery_decision_sha256": "3" * 64,
        "provider_target_receipt_sha256": "4" * 64,
        "target_projection_sha256": "5" * 64,
        "receipt_artifact_sha256": "4" * 64,
        "retention_intent_id": 1,
        "retention_intent_payload_sha256": "6" * 64,
        "retention_event_evidence_sha256": "7" * 64,
        "retention_topology_identity_sha256": "8" * 64,
        "receipt_artifact_file_identity_sha256": "9" * 64,
        "start_receipt_sha256": "a" * 64,
        "terminal_receipt_sha256": "b" * 64,
        "event_store_path": "/tmp/retention/event.sqlite3",
        "receipt_cas_path": "/tmp/retention/cas",
        "admission_identity_bound": True,
        "admission_topology_bound": True,
        "recovery_decision_bound": True,
        "provider_target_receipt_authenticated": True,
        "retention_intent_completed": True,
        "retained_receipt_cas_verified": True,
        "primary_checkout_disjointness_verified": True,
        "retention_topology_stable": True,
        "receipt_artifact_identity_stable": True,
        "persisted_effect_terminal_verified": False,
        "automatic_reexecution_allowed": False,
        "effect_start_authorized": False,
        "retention_write_authorized": False,
        "effect_terminalization_authorized": False,
        "canonical_entrypoint_registered": False,
        "gate_transition_authorized": False,
        "closed": False,
    }


def test_completed_evidence_schema_is_exact_and_non_authorizing() -> None:
    document = _document()

    assert document["type"] == "object"
    assert document["additionalProperties"] is False
    assert set(document["required"]) == set(document["properties"])
    properties = document["properties"]
    for field in (
        "admission_identity_bound",
        "admission_topology_bound",
        "recovery_decision_bound",
        "provider_target_receipt_authenticated",
        "retention_intent_completed",
        "retained_receipt_cas_verified",
        "primary_checkout_disjointness_verified",
        "retention_topology_stable",
        "receipt_artifact_identity_stable",
    ):
        assert properties[field]["const"] is True
    for field in (
        "persisted_effect_terminal_verified",
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert properties[field]["const"] is False

    Draft202012Validator(document).validate(_payload())


def test_completed_evidence_schema_rejects_malformed_identity_and_paths() -> None:
    validator = Draft202012Validator(_document())

    for field, value in (
        ("source_revision", "1" * 39),
        ("source_revision", "G" * 40),
        ("admission_sha256", "2" * 63),
        ("retention_topology_identity_sha256", "8" * 63),
        ("receipt_artifact_file_identity_sha256", "Z" * 64),
        ("retention_intent_id", 0),
        ("retention_intent_id", True),
        ("event_store_path", ""),
        ("receipt_cas_path", "bad\npath"),
    ):
        payload = copy.deepcopy(_payload())
        payload[field] = value
        with pytest.raises(ValidationError):
            validator.validate(payload)


def test_completed_evidence_schema_rejects_claim_escalation_and_extras() -> None:
    validator = Draft202012Validator(_document())

    payload = _payload()
    payload["unexpected"] = False
    with pytest.raises(ValidationError):
        validator.validate(payload)

    for field in (
        "persisted_effect_terminal_verified",
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        payload = copy.deepcopy(_payload())
        payload[field] = True
        with pytest.raises(ValidationError):
            validator.validate(payload)

    for field in (
        "admission_topology_bound",
        "retention_topology_stable",
        "receipt_artifact_identity_stable",
    ):
        payload = copy.deepcopy(_payload())
        payload[field] = False
        with pytest.raises(ValidationError):
            validator.validate(payload)
