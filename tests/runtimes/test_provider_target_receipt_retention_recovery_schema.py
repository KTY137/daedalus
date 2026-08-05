from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


SCHEMA = Path(
    "configs/schemas/provider-target-receipt-retention-recovery-decision.schema.json"
)
_DECISIONS = {
    "not_started": "request_fresh_start_authorization",
    "started": "manual_reconciliation_required",
    "COMPLETED": "verify_completed_retention_evidence",
    "FAILED": "terminal_failure_refusal",
    "CANCELLED": "terminal_cancellation_refusal",
}


def _document() -> dict[str, object]:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


def _payload(state: str = "not_started") -> dict[str, object]:
    started = state != "not_started"
    terminal = state in {"COMPLETED", "FAILED", "CANCELLED"}
    return {
        "schema": (
            "daedalus-provider-target-receipt-retention-recovery-decision/1"
        ),
        "source_revision": "1" * 40,
        "admission_sha256": "2" * 64,
        "execution_state": state,
        "decision": _DECISIONS[state],
        "start_receipt_sha256": "3" * 64 if started else None,
        "terminal_receipt_sha256": "4" * 64 if terminal else None,
        "admission_identity_bound": True,
        "persisted_state_reverified": False,
        "manual_reconciliation_required": state == "started",
        "terminal_state_observed": terminal,
        "automatic_reexecution_allowed": False,
        "effect_start_authorized": False,
        "retention_write_authorized": False,
        "effect_terminalization_authorized": False,
        "canonical_entrypoint_registered": False,
        "gate_transition_authorized": False,
        "closed": False,
    }


def test_recovery_schema_is_exact_and_non_authorizing() -> None:
    document = _document()

    assert document["type"] == "object"
    assert document["additionalProperties"] is False
    assert set(document["required"]) == set(document["properties"])
    properties = document["properties"]
    assert properties["schema"]["const"] == (
        "daedalus-provider-target-receipt-retention-recovery-decision/1"
    )
    assert properties["admission_identity_bound"]["const"] is True
    for field in (
        "persisted_state_reverified",
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert properties[field]["const"] is False


def test_all_exact_recovery_states_validate() -> None:
    validator = Draft202012Validator(_document())

    for state in _DECISIONS:
        validator.validate(_payload(state))


def test_state_decision_receipt_and_derived_claims_are_cross_bound() -> None:
    validator = Draft202012Validator(_document())
    mutations: list[dict[str, object]] = []

    payload = _payload("not_started")
    payload["start_receipt_sha256"] = "3" * 64
    mutations.append(payload)

    payload = _payload("started")
    payload["decision"] = _DECISIONS["not_started"]
    mutations.append(payload)

    payload = _payload("started")
    payload["terminal_receipt_sha256"] = "4" * 64
    mutations.append(payload)

    payload = _payload("COMPLETED")
    payload["terminal_receipt_sha256"] = None
    mutations.append(payload)

    payload = _payload("FAILED")
    payload["terminal_state_observed"] = False
    mutations.append(payload)

    payload = _payload("CANCELLED")
    payload["manual_reconciliation_required"] = True
    mutations.append(payload)

    for payload in mutations:
        with pytest.raises(ValidationError):
            validator.validate(payload)


def test_schema_rejects_extra_fields_malformed_identity_and_claim_escalation() -> None:
    validator = Draft202012Validator(_document())

    payload = _payload()
    payload["unexpected"] = False
    with pytest.raises(ValidationError):
        validator.validate(payload)

    for field, value in (
        ("source_revision", "1" * 39),
        ("source_revision", "G" * 40),
        ("admission_sha256", "2" * 63),
        ("admission_sha256", "Z" * 64),
    ):
        payload = copy.deepcopy(_payload())
        payload[field] = value
        with pytest.raises(ValidationError):
            validator.validate(payload)

    for field in (
        "persisted_state_reverified",
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
