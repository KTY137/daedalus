from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.gates.evidence import FaultMatrixEvidence
from daedalus.gates.fault_matrix import (
    FINGERPRINT_ALGORITHM,
    FaultMatrixBindingError,
    FaultMatrixManifest,
    FaultMatrixShapeError,
    FaultMatrixVerificationReceipt,
    FaultScenarioReceipt,
    FaultScenarioSpec,
    fault_injection_fingerprint,
    verify_fault_matrix_run,
)

MANIFEST_PATH = Path(
    "configs/gates/g0-provider-target-receipt-retention-fault-matrix.json"
)
HARNESS_REVISION = "2" * 40
RUNTIME_SHA256 = "3" * 64
TOOLCHAIN_SHA256 = "4" * 64


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
    fingerprint: str | None = None,
    outcome: str | None = None,
    restart_policy: str | None = None,
    process_termination: bool | None = None,
    markers: tuple[str, ...] | None = None,
    after: str | None = None,
    source_revision: str | None = None,
    harness_revision: str = HARNESS_REVISION,
    runtime_sha256: str = RUNTIME_SHA256,
    toolchain_sha256: str = TOOLCHAIN_SHA256,
    artifact_suffix: str = "",
) -> FaultScenarioReceipt:
    checkout = _sha("primary-checkout")
    return FaultScenarioReceipt(
        scenario_id=spec.scenario_id,
        scenario_spec_sha256=spec.digest,
        source_revision=source_revision or manifest.source_revision,
        harness_revision=harness_revision,
        harness_runtime_sha256=runtime_sha256,
        toolchain_manifest_sha256=toolchain_sha256,
        injection_fingerprint_sha256=(
            fingerprint or manifest.injection_fingerprint(spec)
        ),
        observed_outcome=outcome or spec.expected_outcome,
        observed_restart_policy=restart_policy or spec.restart_policy,
        process_termination_observed=(
            spec.process_termination
            if process_termination is None
            else process_termination
        ),
        durable_markers=(
            spec.expected_durable_markers if markers is None else markers
        ),
        primary_checkout_before_sha256=checkout,
        primary_checkout_after_sha256=after or checkout,
        run_artifact_sha256=_sha(
            f"artifact:{spec.scenario_id}:{artifact_suffix}"
        ),
    )


def _receipts(manifest: FaultMatrixManifest) -> tuple[FaultScenarioReceipt, ...]:
    return tuple(_receipt(manifest, spec) for spec in manifest.scenarios)


def _verify(
    manifest: FaultMatrixManifest,
    receipts: tuple[FaultScenarioReceipt, ...],
) -> FaultMatrixVerificationReceipt:
    return verify_fault_matrix_run(
        manifest,
        receipts,
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
        expected_harness_runtime_sha256=RUNTIME_SHA256,
        expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
    )


def test_manifest_round_trip_is_revision_pinned_non_executing_and_exact() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()

    assert manifest.matrix_id == "g0.provider-target-receipt-retention.v1"
    assert manifest.gate == 0
    assert len(manifest.source_revision) == 40
    assert manifest.subject_entrypoint_id == "provider.target-receipt.retain"
    assert len(manifest.scenarios) == 12
    assert payload["injection_fingerprint_algorithm"] == FINGERPRINT_ALGORITHM
    assert tuple(item.scenario_id for item in manifest.scenarios) == tuple(
        sorted(item.scenario_id for item in manifest.scenarios)
    )
    assert len({item.injection_point for item in manifest.scenarios}) == 12
    assert len(
        {manifest.injection_fingerprint(item) for item in manifest.scenarios}
    ) == 12
    assert payload["inventory_complete_claimed"] is False
    assert payload["faults_executed"] is False
    assert payload["gate_transition_authorized"] is False
    assert payload["closed"] is False
    assert FaultMatrixManifest.from_dict(payload) == manifest


def test_fingerprint_is_exactly_revision_scenario_and_point_bound() -> None:
    manifest = _manifest()
    spec = manifest.scenarios[0]
    expected = manifest.injection_fingerprint(spec)

    assert expected == fault_injection_fingerprint(
        manifest.source_revision,
        spec.scenario_id,
        spec.injection_point,
    )
    assert expected != fault_injection_fingerprint(
        "f" * 40,
        spec.scenario_id,
        spec.injection_point,
    )
    assert expected != fault_injection_fingerprint(
        manifest.source_revision,
        spec.scenario_id,
        "retention.other-point",
    )


def test_exact_complete_run_round_trips_and_projects_existing_gate_evidence() -> None:
    manifest = _manifest()
    receipts = _receipts(manifest)
    verification = _verify(manifest, receipts)
    payload = verification.to_dict()

    assert verification.status == "passed"
    assert verification.failure_count == 0
    for field in (
        "inventory_complete",
        "fingerprints_verified",
        "restart_policies_verified",
        "process_termination_verified",
        "runtime_toolchain_verified",
        "primary_checkout_unchanged",
        "automatic_reexecution_absent",
        "llm_evidence_absent",
    ):
        assert payload[field] is True
    assert payload["gate_transition_authorized"] is False
    assert payload["closed"] is False
    assert FaultMatrixVerificationReceipt.from_dict(payload) == verification

    evidence = verification.to_fault_matrix_evidence(
        manifest,
        receipts,
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
        expected_harness_runtime_sha256=RUNTIME_SHA256,
        expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
    )
    assert type(evidence) is FaultMatrixEvidence
    assert evidence.status == "passed"
    assert evidence.failure_count == 0
    assert evidence.scenario_ids == tuple(
        item.scenario_id for item in manifest.scenarios
    )
    assert evidence.source_revision == manifest.source_revision


def test_missing_extra_duplicate_and_duplicate_artifact_fail_closed() -> None:
    manifest = _manifest()
    receipts = _receipts(manifest)

    missing = _verify(manifest, receipts[1:])
    assert missing.status == "failed"
    assert missing.missing_scenario_ids == (manifest.scenarios[0].scenario_id,)
    with pytest.raises(FaultMatrixBindingError, match="failed fault matrix"):
        missing.to_fault_matrix_evidence(
            manifest,
            receipts[1:],
            expected_source_revision=manifest.source_revision,
            expected_harness_revision=HARNESS_REVISION,
            expected_harness_runtime_sha256=RUNTIME_SHA256,
            expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
        )

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
        harness_runtime_sha256=RUNTIME_SHA256,
        toolchain_manifest_sha256=TOOLCHAIN_SHA256,
        injection_fingerprint_sha256=fault_injection_fingerprint(
            manifest.source_revision,
            extra_spec.scenario_id,
            extra_spec.injection_point,
        ),
        observed_outcome=extra_spec.expected_outcome,
        observed_restart_policy=extra_spec.restart_policy,
        process_termination_observed=False,
        durable_markers=(),
        primary_checkout_before_sha256=_sha("primary"),
        primary_checkout_after_sha256=_sha("primary"),
        run_artifact_sha256=_sha("extra-artifact"),
    )
    extra = _verify(manifest, (*receipts, extra_receipt))
    assert extra.status == "failed"
    assert extra.extra_scenario_ids == (extra_spec.scenario_id,)

    with pytest.raises(FaultMatrixBindingError, match="duplicate scenario receipts"):
        _verify(manifest, (*receipts, receipts[0]))

    duplicate_artifact = replace(
        receipts[1],
        run_artifact_sha256=receipts[0].run_artifact_sha256,
    )
    with pytest.raises(FaultMatrixBindingError, match="run artifacts must be unique"):
        _verify(manifest, (receipts[0], duplicate_artifact, *receipts[2:]))


def test_every_exact_observation_binding_is_required() -> None:
    manifest = _manifest()
    receipts = list(_receipts(manifest))
    spec = manifest.scenarios[0]
    forbidden = spec.forbidden_durable_markers[0]

    mutations = (
        replace(receipts[0], scenario_spec_sha256="f" * 64),
        replace(receipts[0], source_revision="5" * 40),
        replace(receipts[0], harness_revision="6" * 40),
        replace(receipts[0], harness_runtime_sha256="7" * 64),
        replace(receipts[0], toolchain_manifest_sha256="8" * 64),
        replace(receipts[0], injection_fingerprint_sha256="9" * 64),
        replace(receipts[0], observed_outcome="terminal_failure"),
        replace(receipts[0], observed_restart_policy="no_retry"),
        replace(
            receipts[0],
            process_termination_observed=not spec.process_termination,
        ),
        replace(receipts[0], durable_markers=()),
        replace(
            receipts[0],
            durable_markers=tuple(
                sorted((*spec.expected_durable_markers, forbidden))
            ),
        ),
        replace(
            receipts[0],
            primary_checkout_after_sha256=_sha("mutated-primary"),
        ),
    )

    for mutated in mutations:
        result = _verify(manifest, (mutated, *receipts[1:]))
        assert result.status == "failed"
        assert result.failed_scenario_ids == (spec.scenario_id,)
        assert result.failure_count == 1


def test_expected_subject_arguments_are_exact_and_stale_revision_refuses() -> None:
    manifest = _manifest()
    receipts = _receipts(manifest)

    with pytest.raises(FaultMatrixBindingError, match="different source revision"):
        verify_fault_matrix_run(
            manifest,
            receipts,
            expected_source_revision="a" * 40,
            expected_harness_revision=HARNESS_REVISION,
            expected_harness_runtime_sha256=RUNTIME_SHA256,
            expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
        )

    for field, value in (
        ("expected_harness_revision", "short"),
        ("expected_harness_runtime_sha256", "short"),
        ("expected_toolchain_manifest_sha256", "short"),
    ):
        kwargs = {
            "expected_source_revision": manifest.source_revision,
            "expected_harness_revision": HARNESS_REVISION,
            "expected_harness_runtime_sha256": RUNTIME_SHA256,
            "expected_toolchain_manifest_sha256": TOOLCHAIN_SHA256,
        }
        kwargs[field] = value
        with pytest.raises(FaultMatrixShapeError):
            verify_fault_matrix_run(manifest, receipts, **kwargs)


def test_forged_passing_projection_receipt_is_reverified_not_trusted() -> None:
    manifest = _manifest()
    receipts = _receipts(manifest)
    exact = _verify(manifest, receipts)
    forged = replace(exact, harness_runtime_sha256="a" * 64)

    with pytest.raises(FaultMatrixBindingError, match="not the exact verified run"):
        forged.to_fault_matrix_evidence(
            manifest,
            receipts,
            expected_source_revision=manifest.source_revision,
            expected_harness_revision=HARNESS_REVISION,
            expected_harness_runtime_sha256=RUNTIME_SHA256,
            expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
        )


def test_wire_claim_escalation_and_derived_claim_forgery_refuse() -> None:
    manifest = _manifest()
    receipt = _receipts(manifest)[0]
    receipt_payload = receipt.to_dict()
    assert FaultScenarioReceipt.from_dict(receipt_payload) == receipt

    for field in (
        "automatic_reexecution_performed",
        "llm_evidence_used",
        "gate_transition_authorized",
        "closed",
    ):
        candidate = dict(receipt_payload)
        candidate[field] = True
        with pytest.raises(FaultMatrixShapeError, match="unsupported claim"):
            FaultScenarioReceipt.from_dict(candidate)

    verification = _verify(manifest, _receipts(manifest))
    payload = verification.to_dict()
    for field in (
        "inventory_complete",
        "fingerprints_verified",
        "restart_policies_verified",
        "process_termination_verified",
        "runtime_toolchain_verified",
        "primary_checkout_unchanged",
        "automatic_reexecution_absent",
        "llm_evidence_absent",
    ):
        candidate = dict(payload)
        candidate[field] = False
        with pytest.raises(FaultMatrixShapeError, match="derived claims disagree"):
            FaultMatrixVerificationReceipt.from_dict(candidate)

    candidate = dict(payload)
    candidate["closed"] = True
    with pytest.raises(FaultMatrixShapeError, match="unsupported claim"):
        FaultMatrixVerificationReceipt.from_dict(candidate)


def test_manifest_and_scenario_shapes_refuse_authority_and_ambiguity() -> None:
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
