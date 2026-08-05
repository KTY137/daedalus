from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.gates.evidence import FaultMatrixEvidence
from daedalus.gates.fault_matrix import (
    FaultMatrixBindingError,
    FaultMatrixManifest,
    FaultMatrixShapeError,
    FaultScenarioReceipt,
    FaultScenarioSpec,
    verify_fault_matrix_run,
)

MANIFEST_PATH = Path(
    "configs/gates/g0-provider-target-receipt-retention-fault-matrix.json"
)
HARNESS_REVISION = "2" * 40


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest() -> FaultMatrixManifest:
    return FaultMatrixManifest.from_dict(
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    )


def _receipt(
    manifest: FaultMatrixManifest,
    spec: FaultScenarioSpec,
    *,
    outcome: str | None = None,
    markers: tuple[str, ...] | None = None,
    before: str | None = None,
    after: str | None = None,
    source_revision: str | None = None,
    harness_revision: str = HARNESS_REVISION,
) -> FaultScenarioReceipt:
    checkout = before or _sha("primary-checkout")
    return FaultScenarioReceipt(
        scenario_id=spec.scenario_id,
        scenario_spec_sha256=spec.digest,
        source_revision=source_revision or manifest.source_revision,
        harness_revision=harness_revision,
        injection_fingerprint=_sha(f"inject:{spec.scenario_id}"),
        observed_outcome=outcome or spec.expected_outcome,
        durable_markers=markers or spec.expected_durable_markers,
        primary_checkout_before_sha256=checkout,
        primary_checkout_after_sha256=after or checkout,
        run_artifact_sha256=_sha(f"artifact:{spec.scenario_id}"),
    )


def _receipts(manifest: FaultMatrixManifest) -> tuple[FaultScenarioReceipt, ...]:
    return tuple(_receipt(manifest, spec) for spec in manifest.scenarios)


def test_manifest_round_trip_is_revision_pinned_non_executing_and_exact() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()

    assert manifest.matrix_id == "g0.provider-target-receipt-retention.v1"
    assert manifest.gate == 0
    assert len(manifest.source_revision) == 40
    assert manifest.subject_entrypoint_id == "provider.target-receipt.retain"
    assert len(manifest.scenarios) == 12
    assert tuple(item.scenario_id for item in manifest.scenarios) == tuple(
        sorted(item.scenario_id for item in manifest.scenarios)
    )
    assert len({item.injection_point for item in manifest.scenarios}) == 12
    assert payload["inventory_complete_claimed"] is False
    assert payload["faults_executed"] is False
    assert payload["gate_transition_authorized"] is False
    assert payload["closed"] is False
    assert FaultMatrixManifest.from_dict(payload) == manifest


def test_exact_complete_run_projects_to_existing_gate_evidence() -> None:
    manifest = _manifest()
    receipts = _receipts(manifest)

    verification = verify_fault_matrix_run(
        manifest,
        receipts,
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
    )
    payload = verification.to_dict()

    assert verification.status == "passed"
    assert verification.failure_count == 0
    assert payload["inventory_complete"] is True
    assert payload["primary_checkout_unchanged"] is True
    assert payload["automatic_reexecution_absent"] is True
    assert payload["llm_evidence_absent"] is True
    assert payload["gate_transition_authorized"] is False
    assert payload["closed"] is False

    evidence = verification.to_fault_matrix_evidence(manifest)
    assert type(evidence) is FaultMatrixEvidence
    assert evidence.status == "passed"
    assert evidence.failure_count == 0
    assert evidence.scenario_ids == tuple(
        item.scenario_id for item in manifest.scenarios
    )
    assert evidence.source_revision == manifest.source_revision


def test_missing_extra_duplicate_and_detached_revision_fail_closed() -> None:
    manifest = _manifest()
    receipts = _receipts(manifest)

    missing = verify_fault_matrix_run(
        manifest,
        receipts[1:],
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
    )
    assert missing.status == "failed"
    assert missing.missing_scenario_ids == (manifest.scenarios[0].scenario_id,)
    with pytest.raises(FaultMatrixBindingError, match="failed fault matrix"):
        missing.to_fault_matrix_evidence(manifest)

    extra_spec = FaultScenarioSpec(
        scenario_id="retention_unregistered_extra",
        injection_point="retention.unregistered.extra",
        targeted_invariants=("effect.exactly-once",),
        expected_outcome="blocked_before_effect",
        expected_durable_markers=(),
        forbidden_durable_markers=("effect.start",),
        restart_policy="no_retry",
        process_termination=False,
    )
    extra_receipt = FaultScenarioReceipt(
        scenario_id=extra_spec.scenario_id,
        scenario_spec_sha256=extra_spec.digest,
        source_revision=manifest.source_revision,
        harness_revision=HARNESS_REVISION,
        injection_fingerprint=_sha("extra-injection"),
        observed_outcome=extra_spec.expected_outcome,
        durable_markers=(),
        primary_checkout_before_sha256=_sha("primary"),
        primary_checkout_after_sha256=_sha("primary"),
        run_artifact_sha256=_sha("extra-artifact"),
    )
    extra = verify_fault_matrix_run(
        manifest,
        (*receipts, extra_receipt),
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
    )
    assert extra.status == "failed"
    assert extra.extra_scenario_ids == (extra_spec.scenario_id,)

    with pytest.raises(FaultMatrixBindingError, match="duplicate scenario receipts"):
        verify_fault_matrix_run(
            manifest,
            (*receipts, receipts[0]),
            expected_source_revision=manifest.source_revision,
            expected_harness_revision=HARNESS_REVISION,
        )

    with pytest.raises(FaultMatrixBindingError, match="different source revision"):
        verify_fault_matrix_run(
            manifest,
            receipts,
            expected_source_revision="3" * 40,
            expected_harness_revision=HARNESS_REVISION,
        )


def test_outcome_marker_checkout_spec_source_and_harness_mismatches_fail() -> None:
    manifest = _manifest()
    receipts = list(_receipts(manifest))
    spec = manifest.scenarios[0]

    mutations = (
        replace(receipts[0], observed_outcome="terminal_failure"),
        replace(receipts[0], durable_markers=()),
        replace(
            receipts[0],
            durable_markers=tuple(
                sorted((*spec.expected_durable_markers, *spec.forbidden_durable_markers))
            ),
        ),
        replace(receipts[0], primary_checkout_after_sha256=_sha("mutated")),
        replace(receipts[0], scenario_spec_sha256="f" * 64),
        replace(receipts[0], source_revision="4" * 40),
        replace(receipts[0], harness_revision="5" * 40),
    )

    for mutated in mutations:
        candidate = tuple([mutated, *receipts[1:]])
        verification = verify_fault_matrix_run(
            manifest,
            candidate,
            expected_source_revision=manifest.source_revision,
            expected_harness_revision=HARNESS_REVISION,
        )
        assert verification.status == "failed"
        assert verification.failed_scenario_ids == (spec.scenario_id,)
        assert verification.failure_count == 1


def test_scenario_receipt_wire_refuses_llm_reexecution_and_claim_escalation() -> None:
    manifest = _manifest()
    receipt = _receipt(manifest, manifest.scenarios[0])
    payload = receipt.to_dict()
    assert FaultScenarioReceipt.from_dict(payload) == receipt

    for field in (
        "automatic_reexecution_performed",
        "llm_evidence_used",
        "gate_transition_authorized",
        "closed",
    ):
        candidate = dict(payload)
        candidate[field] = True
        with pytest.raises(FaultMatrixShapeError, match="unsupported claim"):
            FaultScenarioReceipt.from_dict(candidate)

    candidate = dict(payload)
    candidate["unexpected"] = False
    with pytest.raises(FaultMatrixShapeError, match="fields are not exact"):
        FaultScenarioReceipt.from_dict(candidate)


def test_manifest_wire_refuses_inventory_execution_gate_and_closure_claims() -> None:
    payload = _manifest().to_dict()
    for field in (
        "inventory_complete_claimed",
        "faults_executed",
        "gate_transition_authorized",
        "closed",
    ):
        candidate = json.loads(json.dumps(payload))
        candidate[field] = True
        with pytest.raises(FaultMatrixShapeError, match="unsupported claim"):
            FaultMatrixManifest.from_dict(candidate)


def test_scenario_shape_refuses_overlap_unsorted_duplicates_and_unknown_values() -> None:
    base = FaultScenarioSpec(
        scenario_id="scenario.valid",
        injection_point="point.valid",
        targeted_invariants=("invariant.a",),
        expected_outcome="blocked_before_effect",
        expected_durable_markers=("marker.a",),
        forbidden_durable_markers=("marker.b",),
        restart_policy="no_retry",
        process_termination=False,
    )

    with pytest.raises(FaultMatrixShapeError, match="must be disjoint"):
        replace(base, forbidden_durable_markers=("marker.a",))
    with pytest.raises(FaultMatrixShapeError, match="sorted canonically"):
        replace(base, targeted_invariants=("invariant.z", "invariant.a"))
    with pytest.raises(FaultMatrixShapeError, match="duplicates"):
        replace(base, targeted_invariants=("invariant.a", "invariant.a"))
    with pytest.raises(FaultMatrixShapeError, match="expected_outcome is unknown"):
        replace(base, expected_outcome="trusted")
    with pytest.raises(FaultMatrixShapeError, match="restart_policy is unknown"):
        replace(base, restart_policy="automatic_retry")
