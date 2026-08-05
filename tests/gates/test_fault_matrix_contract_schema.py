from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from daedalus.gates.fault_matrix import (
    FaultMatrixManifest,
    FaultScenarioReceipt,
    verify_fault_matrix_run,
)

SCHEMA_PATH = Path("configs/schemas/fault-matrix-contract.schema.json")
MANIFEST_PATH = Path(
    "configs/gates/g0-provider-target-receipt-retention-fault-matrix.json"
)
HARNESS_REVISION = "2" * 40


def _schema() -> dict[str, object]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _manifest_payload() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _manifest() -> FaultMatrixManifest:
    return FaultMatrixManifest.from_dict(_manifest_payload())


def _receipt(manifest: FaultMatrixManifest, index: int) -> FaultScenarioReceipt:
    spec = manifest.scenarios[index]
    digest = f"{index + 1:x}" * 64
    return FaultScenarioReceipt(
        scenario_id=spec.scenario_id,
        scenario_spec_sha256=spec.digest,
        source_revision=manifest.source_revision,
        harness_revision=HARNESS_REVISION,
        injection_fingerprint=digest,
        observed_outcome=spec.expected_outcome,
        durable_markers=spec.expected_durable_markers,
        primary_checkout_before_sha256="a" * 64,
        primary_checkout_after_sha256="a" * 64,
        run_artifact_sha256="b" * 64,
    )


def test_schema_and_pinned_manifest_validate() -> None:
    validator = Draft202012Validator(_schema())
    payload = _manifest_payload()

    validator.validate(payload)
    assert payload["scenario_count"] == len(payload["scenarios"]) == 12
    assert payload["inventory_complete_claimed"] is False
    assert payload["faults_executed"] is False
    assert payload["gate_transition_authorized"] is False
    assert payload["closed"] is False


def test_scenario_and_passing_verification_receipts_validate() -> None:
    validator = Draft202012Validator(_schema())
    manifest = _manifest()
    receipts = tuple(_receipt(manifest, index) for index in range(len(manifest.scenarios)))

    for receipt in receipts:
        validator.validate(receipt.to_dict())

    verification = verify_fault_matrix_run(
        manifest,
        receipts,
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
    )
    validator.validate(verification.to_dict())
    assert verification.to_dict()["status"] == "passed"


def test_schema_rejects_manifest_and_scenario_authority_escalation() -> None:
    validator = Draft202012Validator(_schema())
    payload = _manifest_payload()

    for field in (
        "inventory_complete_claimed",
        "faults_executed",
        "gate_transition_authorized",
        "closed",
    ):
        candidate = copy.deepcopy(payload)
        candidate[field] = True
        with pytest.raises(ValidationError):
            validator.validate(candidate)

    scenario = copy.deepcopy(payload["scenarios"][0])
    for field in (
        "automatic_reexecution_allowed",
        "primary_checkout_mutation_allowed",
        "llm_evidence_allowed",
    ):
        candidate = copy.deepcopy(payload)
        candidate["scenarios"][0][field] = True
        with pytest.raises(ValidationError):
            validator.validate(candidate)


def test_schema_rejects_receipt_reexecution_llm_gate_and_closure_claims() -> None:
    validator = Draft202012Validator(_schema())
    payload = _receipt(_manifest(), 0).to_dict()

    for field in (
        "automatic_reexecution_performed",
        "llm_evidence_used",
        "gate_transition_authorized",
        "closed",
    ):
        candidate = copy.deepcopy(payload)
        candidate[field] = True
        with pytest.raises(ValidationError):
            validator.validate(candidate)


def test_schema_rejects_passing_verification_with_any_false_safety_claim() -> None:
    validator = Draft202012Validator(_schema())
    manifest = _manifest()
    receipts = tuple(_receipt(manifest, index) for index in range(len(manifest.scenarios)))
    payload = verify_fault_matrix_run(
        manifest,
        receipts,
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
    ).to_dict()

    for field in (
        "inventory_complete",
        "primary_checkout_unchanged",
        "automatic_reexecution_absent",
        "llm_evidence_absent",
    ):
        candidate = copy.deepcopy(payload)
        candidate[field] = False
        with pytest.raises(ValidationError):
            validator.validate(candidate)

    candidate = copy.deepcopy(payload)
    candidate["failure_count"] = 1
    with pytest.raises(ValidationError):
        validator.validate(candidate)

    candidate = copy.deepcopy(payload)
    candidate["unexpected"] = False
    with pytest.raises(ValidationError):
        validator.validate(candidate)
