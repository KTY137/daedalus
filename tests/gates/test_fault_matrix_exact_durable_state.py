# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.gates.fault_matrix import (
    FaultMatrixManifest,
    FaultMatrixShapeError,
    FaultMatrixVerificationReceipt,
    FaultScenarioReceipt,
    verify_fault_matrix_run,
)

MANIFEST_PATH = Path(
    "configs/gates/g0-provider-target-receipt-retention-fault-matrix.json"
)
HARNESS_REVISION = "2" * 40
RUNTIME_SHA256 = "3" * 64
TOOLCHAIN_SHA256 = "4" * 64


def _manifest() -> FaultMatrixManifest:
    return FaultMatrixManifest.from_dict(
        json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    )


def _receipt(
    manifest: FaultMatrixManifest,
    index: int,
) -> FaultScenarioReceipt:
    spec = manifest.scenarios[index]
    return FaultScenarioReceipt(
        scenario_id=spec.scenario_id,
        scenario_spec_sha256=spec.digest,
        source_revision=manifest.source_revision,
        harness_revision=HARNESS_REVISION,
        harness_runtime_sha256=RUNTIME_SHA256,
        toolchain_manifest_sha256=TOOLCHAIN_SHA256,
        injection_fingerprint_sha256=manifest.injection_fingerprint(spec),
        observed_outcome=spec.expected_outcome,
        observed_restart_policy=spec.restart_policy,
        process_termination_observed=spec.process_termination,
        durable_markers=spec.expected_durable_markers,
        primary_checkout_before_sha256="a" * 64,
        primary_checkout_after_sha256="a" * 64,
        run_artifact_sha256=f"{index + 1:x}" * 64,
    )


def test_unlisted_nonforbidden_durable_marker_fails_exact_state() -> None:
    manifest = _manifest()
    receipts = tuple(
        _receipt(manifest, index) for index in range(len(manifest.scenarios))
    )
    spec = manifest.scenarios[0]
    mutated = replace(
        receipts[0],
        durable_markers=tuple(
            sorted((*spec.expected_durable_markers, "unexpected.marker"))
        ),
    )

    result = verify_fault_matrix_run(
        manifest,
        (mutated, *receipts[1:]),
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
        expected_harness_runtime_sha256=RUNTIME_SHA256,
        expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
    )

    assert result.status == "failed"
    assert result.failed_scenario_ids == (spec.scenario_id,)
    assert result.to_dict()["exact_durable_states_verified"] is False


def test_passing_wire_requires_exact_durable_state_claim() -> None:
    manifest = _manifest()
    receipts = tuple(
        _receipt(manifest, index) for index in range(len(manifest.scenarios))
    )
    result = verify_fault_matrix_run(
        manifest,
        receipts,
        expected_source_revision=manifest.source_revision,
        expected_harness_revision=HARNESS_REVISION,
        expected_harness_runtime_sha256=RUNTIME_SHA256,
        expected_toolchain_manifest_sha256=TOOLCHAIN_SHA256,
    )
    payload = result.to_dict()
    assert payload["exact_durable_states_verified"] is True

    payload["exact_durable_states_verified"] = False
    with pytest.raises(FaultMatrixShapeError, match="derived claims disagree"):
        FaultMatrixVerificationReceipt.from_dict(payload)
