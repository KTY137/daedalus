# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The two live probes, and the ways they must refuse to claim a pass.

Both catalog rows expect ``refused-before-start``. The danger with a row whose
success condition is "something was refused" is that almost any breakage
produces a refusal, so these tests spend most of their effort on the cases where
a refusal happened and the probe must still *not* report a pass.
"""
from __future__ import annotations

import hashlib
import inspect
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.runtime_conformance import verify_current_conformance
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.live_probe_drivers import (
    BINARY_DRIFT_LOCATOR,
    EXPIRY_LOCATOR,
    LiveProbeUnavailable,
    build_live_probe_executors,
    drift_binary_copy,
    load_live_envelope_bundle,
    measure_file_sha256,
    probe_binary_drift,
    probe_envelope_expiry,
)

from live_column_fixtures import build_live_bundle

EXPIRY_SCENARIO = RUNTIME_FAULT_CATALOG.scenario_map["runtime.live-envelope.expiry"]
DRIFT_SCENARIO = RUNTIME_FAULT_CATALOG.scenario_map["runtime.live-envelope.binary-drift"]


def _facts(result) -> dict[str, str]:
    return {fact.name: fact.value for fact in result.facts}


def test_expiry_probe_passes_only_after_its_control_was_accepted(tmp_path: Path) -> None:
    bundle = build_live_bundle(tmp_path)
    result = probe_envelope_expiry(EXPIRY_SCENARIO, live_envelope_dir=bundle.bundle_dir)

    assert result.status == "passed"
    assert result.observed_outcome == "refused-before-start"
    facts = _facts(result)
    # The pass is only meaningful because the same bundle was accepted first.
    assert facts["control"] == "accepted-when-fresh"
    assert "stale" in facts["refusal-message"]
    assert facts["envelope-authority"] == "live-runtime"


def test_expiry_probe_ages_by_the_bound_the_kernel_itself_enforces(
    tmp_path: Path,
) -> None:
    """The probe must test the kernel's instant, not a number copied beside it."""

    bundle = build_live_bundle(tmp_path)
    result = probe_envelope_expiry(EXPIRY_SCENARIO, live_envelope_dir=bundle.bundle_dir)
    kernel_default = inspect.signature(verify_current_conformance).parameters[
        "max_age"
    ].default

    assert _facts(result)["kernel-max-age-seconds"] == str(
        int(kernel_default.total_seconds())
    )
    # One second inside the bound the receipt is still current, so the probe
    # would have proven nothing had it aged the envelope by any less.
    verify_current_conformance(
        bundle.receipt,
        bundle.manifest,
        now=bundle.finished_at + kernel_default - timedelta(seconds=1),
    )


def test_expiry_probe_blocks_without_live_evidence(tmp_path: Path) -> None:
    result = probe_envelope_expiry(EXPIRY_SCENARIO, live_envelope_dir=None)

    assert result.status == "blocked"
    assert result.observed_outcome is None
    assert result.detail_code == "live-envelope-unavailable"


def test_offline_fixture_evidence_cannot_enter_the_live_column(tmp_path: Path) -> None:
    """An offline bundle is refused by name rather than laundered into a pass."""

    bundle = build_live_bundle(tmp_path, authority="offline-fixture")
    result = probe_envelope_expiry(EXPIRY_SCENARIO, live_envelope_dir=bundle.bundle_dir)

    assert result.status == "blocked"
    assert result.detail_code == "envelope-not-live"
    assert "offline-fixture" in _facts(result)["blocked-detail"]


def test_a_failed_conformance_bundle_blocks_instead_of_passing(tmp_path: Path) -> None:
    """A bundle refused for its own status would refuse the fault too, meaninglessly."""

    bundle = build_live_bundle(tmp_path, all_checks_pass=False)
    result = probe_envelope_expiry(EXPIRY_SCENARIO, live_envelope_dir=bundle.bundle_dir)

    assert result.status == "blocked"
    assert result.detail_code == "envelope-not-passed"


def test_a_rejected_control_blocks_instead_of_passing(tmp_path: Path) -> None:
    """The decisive anti-cheat case: refused when fresh means the row proves nothing."""

    good = build_live_bundle(tmp_path / "good")
    other = build_live_bundle(tmp_path / "other", revision="c" * 40)
    # Swap in a manifest the envelope never bound. Every later verification now
    # refuses -- including the injected one, which is precisely why a refusal
    # here must not be counted as the expiry guard firing.
    (good.bundle_dir / "ollama_http-manifest.json").write_text(
        other.manifest.to_json(), encoding="utf-8"
    )
    result = probe_envelope_expiry(EXPIRY_SCENARIO, live_envelope_dir=good.bundle_dir)

    assert result.status == "blocked"
    assert result.detail_code == "control-rejected"


def test_drift_probe_passes_only_with_all_three_refusals(tmp_path: Path) -> None:
    bundle = build_live_bundle(tmp_path)
    result = probe_binary_drift(
        DRIFT_SCENARIO,
        live_envelope_dir=bundle.bundle_dir,
        provider_binary=bundle.provider_binary,
    )

    assert result.status == "passed"
    assert result.observed_outcome == "refused-before-start"
    facts = _facts(result)
    assert facts["control"] == "accepted-before-drift"
    assert facts["measured-executable-sha256"] != facts["drifted-executable-sha256"]
    assert "does not bind probe component digest" in facts["rebind-refusal"]
    assert "probe_identity_sha256" in facts["quarantine-refusal"]
    assert "trusted evidence set" in facts["fallback-refusal"]


def test_drift_probe_never_writes_to_the_installed_binary(tmp_path: Path) -> None:
    bundle = build_live_bundle(tmp_path)
    before = measure_file_sha256(bundle.provider_binary)
    probe_binary_drift(
        DRIFT_SCENARIO,
        live_envelope_dir=bundle.bundle_dir,
        provider_binary=bundle.provider_binary,
    )

    assert measure_file_sha256(bundle.provider_binary) == before


def test_drift_probe_blocks_when_the_envelope_describes_another_binary(
    tmp_path: Path,
) -> None:
    bundle = build_live_bundle(tmp_path)
    stranger = tmp_path / "stranger.bin"
    stranger.write_bytes(b"a different provider image entirely")

    result = probe_binary_drift(
        DRIFT_SCENARIO,
        live_envelope_dir=bundle.bundle_dir,
        provider_binary=stranger,
    )

    assert result.status == "blocked"
    assert result.detail_code == "binary-identity-unbound"


def test_drift_probe_blocks_without_a_provider_binary(tmp_path: Path) -> None:
    bundle = build_live_bundle(tmp_path)
    result = probe_binary_drift(
        DRIFT_SCENARIO, live_envelope_dir=bundle.bundle_dir, provider_binary=None
    )

    assert result.status == "blocked"
    assert result.detail_code == "provider-binary-unavailable"


def test_drift_measurement_is_of_real_bytes(tmp_path: Path) -> None:
    target = tmp_path / "image.bin"
    target.write_bytes(b"original image")
    original, drifted = drift_binary_copy(target)

    assert original == hashlib.sha256(b"original image").hexdigest()
    assert drifted != original
    # The installed image is untouched; only an isolated copy was mutated.
    assert target.read_bytes() == b"original image"


def test_bundle_loader_refuses_an_ambiguous_directory(tmp_path: Path) -> None:
    bundle = build_live_bundle(tmp_path)
    (bundle.bundle_dir / "second-envelope.json").write_text(
        bundle.envelope.to_json(), encoding="utf-8"
    )

    with pytest.raises(LiveProbeUnavailable) as excinfo:
        load_live_envelope_bundle(bundle.bundle_dir)
    assert excinfo.value.reason == "live-envelope-ambiguous"


def test_executor_bindings_match_the_catalog_locators() -> None:
    executors = build_live_probe_executors()

    assert set(executors) == {EXPIRY_LOCATOR, BINARY_DRIFT_LOCATOR}
    assert EXPIRY_SCENARIO.executor == EXPIRY_LOCATOR
    assert DRIFT_SCENARIO.executor == BINARY_DRIFT_LOCATOR
    for locator, binding in executors.items():
        assert binding.locator == locator
