from __future__ import annotations

import dataclasses
import hashlib

import pytest

from daedalus.runtimes.faults import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultCatalog,
    RuntimeFaultMatrix,
    RuntimeFaultObservation,
    RuntimeFaultScenario,
    build_runtime_fault_matrix,
    verify_runtime_fault_matrix,
)
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
NOW = "2026-08-03T04:00:00+00:00"
_DEFAULT_OUTCOME = object()


def _evidence(scenario_id: str) -> str:
    return hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()


def _observation(
    scenario: RuntimeFaultScenario,
    *,
    status: str = "passed",
    revision: str = REVISION,
    authority: str | None = None,
    scenario_sha256: str | None = None,
    observed_outcome: str | None | object = _DEFAULT_OUTCOME,
) -> RuntimeFaultObservation:
    evidence = _evidence(scenario.scenario_id)
    scenario_digest = scenario_sha256 or scenario.digest
    if observed_outcome is _DEFAULT_OUTCOME:
        outcome = None if status == "blocked" else scenario.expected_outcome
    else:
        outcome = observed_outcome
    return RuntimeFaultObservation(
        observation_id=f"obs.{scenario.scenario_id}",
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario_digest,
        source_revision=revision,
        authority=authority or scenario.authority,
        status=status,
        observed_outcome=outcome,  # type: ignore[arg-type]
        observed_at=NOW,
        evidence_sha256=evidence,
        detail_code=None if status == "passed" else f"observed.{status}",
        provenance=ContractProvenance(
            origin="tests.runtime-fault-catalog",
            source_revision=revision,
            created_at=NOW,
            input_digests=tuple(sorted((scenario_digest, evidence))),
        ),
    )


def _matrix(
    observations=(),
    *,
    catalog: RuntimeFaultCatalog = RUNTIME_FAULT_CATALOG,
    revision: str = REVISION,
) -> RuntimeFaultMatrix:
    return build_runtime_fault_matrix(
        matrix_id="gate0-runtime-faults",
        source_revision=revision,
        observations=tuple(observations),
        generated_at=NOW,
        catalog=catalog,
        provenance_origin="tests.runtime-fault-matrix",
    )


def _trusted(observations) -> tuple[str, ...]:
    return tuple(row.digest for row in observations)


def _verify(matrix: RuntimeFaultMatrix, trusted=(), *, revision: str = REVISION):
    return verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=revision,
        trusted_observation_digests=tuple(trusted),
    )


def test_catalog_is_deterministic_round_trippable_and_authority_explicit() -> None:
    catalog = RUNTIME_FAULT_CATALOG
    assert len(catalog.scenarios) == 24
    assert tuple(row.scenario_id for row in catalog.scenarios) == tuple(
        sorted(row.scenario_id for row in catalog.scenarios)
    )
    assert {row.authority for row in catalog.scenarios} == {
        "deterministic-fixture",
        "linux-host",
        "live-runtime",
    }
    assert all(row.required_for_gate0 for row in catalog.scenarios)
    assert RuntimeFaultCatalog.from_dict(catalog.to_dict()) == catalog
    assert RuntimeFaultCatalog.from_dict(catalog.to_dict()).digest == catalog.digest


def test_empty_matrix_is_fail_closed_for_every_required_scenario() -> None:
    matrix = _matrix()
    verification = _verify(matrix)

    required = {
        f"fault.missing:{row.scenario_id}"
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.required_for_gate0
    }
    assert set(verification.blockers) == required
    assert verification.closed is False
    assert verification.trusted_observation_sha256s == ()
    assert "closed" not in matrix.to_dict()
    assert verification.to_dict()["closed"] is False


def test_candidate_pass_claims_are_blocked_without_external_trust() -> None:
    observations = [_observation(row) for row in RUNTIME_FAULT_CATALOG.scenarios]
    verification = _verify(_matrix(observations), trusted=())

    assert verification.closed is False
    assert set(verification.blockers) == {
        f"fault.untrusted-observation:{row.scenario_id}"
        for row in RUNTIME_FAULT_CATALOG.scenarios
    }


def test_deterministic_success_cannot_hide_missing_host_or_live_authority() -> None:
    deterministic = [
        _observation(row)
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.authority == "deterministic-fixture"
    ]
    verification = _verify(_matrix(deterministic), trusted=_trusted(deterministic))

    assert verification.closed is False
    assert any("runtime.live-envelope.expiry" in row for row in verification.blockers)
    assert any("runtime.process.timeout" in row for row in verification.blockers)
    assert not any(
        row.startswith("fault.missing:runtime.broker")
        for row in verification.blockers
    )
    assert not any(
        row.startswith("fault.untrusted-observation")
        for row in verification.blockers
    )


def test_exact_complete_catalog_closes_only_with_trusted_passed_observations() -> None:
    observations = [_observation(row) for row in RUNTIME_FAULT_CATALOG.scenarios]
    matrix = _matrix(observations)
    verification = _verify(matrix, trusted=_trusted(observations))

    assert RuntimeFaultMatrix.from_dict(matrix.to_dict()) == matrix
    assert verification.blockers == ()
    assert verification.closed is True
    assert verification.trusted_observation_sha256s == tuple(
        sorted(row.digest for row in observations)
    )
    round_trip = RuntimeFaultMatrix.from_dict(matrix.to_dict())
    assert verification.digest == _verify(
        round_trip,
        trusted=_trusted(round_trip.observations),
    ).digest


def test_trusted_pass_record_with_wrong_terminal_outcome_is_a_blocker() -> None:
    target = RUNTIME_FAULT_CATALOG.scenarios[0]
    wrong = next(value for value in ("failed", "cancelled") if value != target.expected_outcome)
    observations = [
        _observation(row, observed_outcome=wrong if row == target else row.expected_outcome)
        for row in RUNTIME_FAULT_CATALOG.scenarios
    ]
    verification = _verify(_matrix(observations), trusted=_trusted(observations))

    assert f"fault.outcome-mismatch:{target.scenario_id}" in verification.blockers
    assert verification.closed is False


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_nonpassing_observation_is_named_even_when_record_is_trusted(status: str) -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenarios[0]
    observations = [
        _observation(row, status=status if row == scenario else "passed")
        for row in RUNTIME_FAULT_CATALOG.scenarios
    ]
    verification = _verify(_matrix(observations), trusted=_trusted(observations))
    assert f"fault.{status}:{scenario.scenario_id}" in verification.blockers
    assert verification.closed is False


def test_passed_requires_observed_outcome_and_blocked_cannot_invent_one() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenarios[0]
    with pytest.raises(ValueError, match="require observed_outcome"):
        _observation(scenario, observed_outcome=None)
    with pytest.raises(ValueError, match="must not invent"):
        _observation(scenario, status="blocked", observed_outcome="failed")


def test_catalog_shrink_foreign_scenario_drift_and_authority_substitution_refuse() -> None:
    canonical = RUNTIME_FAULT_CATALOG
    first = canonical.scenarios[0]
    second = canonical.scenarios[1]
    wrong_authority = (
        "linux-host" if second.authority != "linux-host" else "live-runtime"
    )
    foreign = RuntimeFaultScenario(
        scenario_id="runtime.foreign.injected",
        boundary="broker",
        authority="deterministic-fixture",
        injection="invent a candidate-local scenario",
        expected_outcome="failed",
        invariant="foreign scenarios cannot satisfy canonical requirements",
        executor="pytest:tests/fake.py::test_fake",
    )
    observations = [
        _observation(first, scenario_sha256="f" * 64),
        _observation(second, authority=wrong_authority),
        _observation(foreign),
    ]
    subset = RuntimeFaultCatalog(
        catalog_id="candidate-shrunk-runtime-faults",
        scenarios=(first, second),
    )
    matrix = _matrix(observations, catalog=subset)
    verification = _verify(matrix, trusted=_trusted(observations))

    assert "fault.catalog-mismatch" in verification.blockers
    assert f"fault.scenario-drift:{first.scenario_id}" in verification.blockers
    assert f"fault.authority-mismatch:{second.scenario_id}" in verification.blockers
    assert f"fault.foreign-scenario:{foreign.scenario_id}" in verification.blockers
    assert verification.closed is False


def test_stale_revision_and_mixed_revision_are_refused() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenarios[0]
    observation = _observation(scenario)
    matrix = _matrix((observation,))
    stale = _verify(matrix, trusted=(observation.digest,), revision=OTHER_REVISION)
    assert "fault.matrix-stale-revision" in stale.blockers
    assert f"fault.stale-revision:{scenario.scenario_id}" in stale.blockers

    with pytest.raises(ValueError, match="exact source revision"):
        _matrix((_observation(scenario, revision=OTHER_REVISION),))


def test_malformed_wire_duplicate_observation_and_repacked_provenance_refuse() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenarios[0]
    observation = _observation(scenario)
    matrix = _matrix((observation,))

    malformed = matrix.to_dict()
    malformed["observations"] = "not-an-array"
    with pytest.raises(ValueError, match="must be an array"):
        RuntimeFaultMatrix.from_dict(malformed)

    with pytest.raises(ValueError, match="duplicate scenario"):
        _matrix((observation, dataclasses.replace(observation, observation_id="obs.other")))

    with pytest.raises(ValueError, match="exact scenario and evidence"):
        dataclasses.replace(
            observation,
            provenance=dataclasses.replace(
                observation.provenance,
                input_digests=(observation.evidence_sha256,),
            ),
        )

    payload = RUNTIME_FAULT_CATALOG.to_dict()
    payload["scenarios"] = "runtime.broker.exact-replay-inert"
    with pytest.raises(ValueError, match="must be an array"):
        RuntimeFaultCatalog.from_dict(payload)


def test_trusted_observation_set_rejects_string_duplicates_and_malformed_hashes() -> None:
    matrix = _matrix()
    with pytest.raises(ValueError, match="must be an array"):
        verify_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            trusted_observation_digests="a" * 64,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="must be unique"):
        _verify(matrix, trusted=("c" * 64, "c" * 64))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _verify(matrix, trusted=("not-a-digest",))
