# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


SCHEMA = Path(
    "configs/schemas/provider-target-receipt-retention-admission.schema.json"
)


def _document() -> dict[str, object]:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


def _payload(state: str = "not_started") -> dict[str, object]:
    terminal = state in {"COMPLETED", "FAILED", "CANCELLED"}
    started = state != "not_started"
    return {
        "schema": "daedalus-provider-target-receipt-retention-admission/1",
        "source_revision": "1" * 40,
        "preflight_sha256": "2" * 64,
        "provider_target_receipt_sha256": "3" * 64,
        "retention_inventory_sha256": "4" * 64,
        "retention_authority_sha256": "5" * 64,
        "retention_execution_request_sha256": "6" * 64,
        "retention_effect_lease_sha256": "7" * 64,
        "retention_effect_lease_request_sha256": "8" * 64,
        "retention_policy_decision_sha256": "9" * 64,
        "guard_contract": "provider.target_receipt_retention",
        "guard_evidence": (
            f"authority_sha256={'a' * 64};subject_sha256={'b' * 64}"
        ),
        "execution_state": state,
        "start_receipt_sha256": "c" * 64 if started else None,
        "terminal_receipt_sha256": "d" * 64 if terminal else None,
        "primary_checkout_path": "/work/primary",
        "retention_root_path": "/work/retention",
        "event_store_path": "/work/retention/state/spine.sqlite3",
        "receipt_cas_path": "/work/retention/cas/receipts",
        "effect_lease_store_path": "/work/effects/effects.sqlite3",
        "persisted_effect_lease_verified": True,
        "primary_checkout_disjointness_verified": True,
        "retention_effect_started": started,
        "retention_effect_terminal": terminal,
        "retention_write_performed": False,
        "automatic_reexecution_allowed": False,
        "canonical_entrypoint_registered": False,
        "gate_transition_authorized": False,
        "closed": False,
    }


def test_admission_schema_is_exact_and_non_authorizing() -> None:
    document = _document()

    assert document["type"] == "object"
    assert document["additionalProperties"] is False
    assert set(document["required"]) == set(document["properties"])
    properties = document["properties"]
    assert properties["schema"]["const"] == (
        "daedalus-provider-target-receipt-retention-admission/1"
    )
    assert properties["persisted_effect_lease_verified"]["const"] is True
    assert properties["primary_checkout_disjointness_verified"]["const"] is True
    for field in (
        "retention_write_performed",
        "automatic_reexecution_allowed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert properties[field]["const"] is False


def test_admission_schema_binds_revision_digests_guard_and_concrete_paths() -> None:
    document = _document()
    properties = document["properties"]

    assert properties["source_revision"]["pattern"] == "^[0-9a-f]{40}$"
    for field in (
        "preflight_sha256",
        "provider_target_receipt_sha256",
        "retention_inventory_sha256",
        "retention_authority_sha256",
        "retention_execution_request_sha256",
        "retention_effect_lease_sha256",
        "retention_effect_lease_request_sha256",
        "retention_policy_decision_sha256",
    ):
        assert properties[field] == {"$ref": "#/$defs/sha256"}
    assert properties["guard_contract"]["const"] == (
        "provider.target_receipt_retention"
    )
    assert "authority_sha256" in properties["guard_evidence"]["pattern"]
    assert "subject_sha256" in properties["guard_evidence"]["pattern"]
    concrete = document["$defs"]["concretePath"]
    assert concrete["minLength"] == 1
    assert concrete["maxLength"] == 4096


def test_all_exact_execution_states_validate() -> None:
    validator = Draft202012Validator(_document())

    for state in (
        "not_started",
        "started",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ):
        validator.validate(_payload(state))


def test_execution_state_receipt_and_claim_combinations_fail_closed() -> None:
    validator = Draft202012Validator(_document())
    mutations = []

    payload = _payload("not_started")
    payload["start_receipt_sha256"] = "c" * 64
    mutations.append(payload)

    payload = _payload("started")
    payload["terminal_receipt_sha256"] = "d" * 64
    mutations.append(payload)

    payload = _payload("COMPLETED")
    payload["terminal_receipt_sha256"] = None
    mutations.append(payload)

    payload = _payload("FAILED")
    payload["retention_effect_terminal"] = False
    mutations.append(payload)

    payload = _payload("CANCELLED")
    payload["automatic_reexecution_allowed"] = True
    mutations.append(payload)

    for payload in mutations:
        with pytest.raises(ValidationError):
            validator.validate(payload)


def test_schema_rejects_extra_fields_malformed_paths_and_claim_escalation() -> None:
    validator = Draft202012Validator(_document())

    payload = _payload()
    payload["unexpected"] = False
    with pytest.raises(ValidationError):
        validator.validate(payload)

    for value in ("", "bad\x00path", "bad\npath", "bad\rpath"):
        payload = _payload()
        payload["event_store_path"] = value
        with pytest.raises(ValidationError):
            validator.validate(payload)

    for field in (
        "retention_write_performed",
        "automatic_reexecution_allowed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        payload = copy.deepcopy(_payload())
        payload[field] = True
        with pytest.raises(ValidationError):
            validator.validate(payload)
