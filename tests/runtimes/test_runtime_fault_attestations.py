# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.runtimes.fault_attestations import (
    RuntimeFaultAttestation,
    RuntimeFaultAttestationBindingMismatch,
    RuntimeFaultAttestationExpired,
    RuntimeFaultAttestationReplay,
    RuntimeFaultAttestationSignatureError,
    issue_runtime_fault_attestation,
    verify_attested_runtime_fault_matrix,
    verify_runtime_fault_attestation,
)
from daedalus.runtimes.faults import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultObservation,
    RuntimeFaultScenario,
    build_runtime_fault_matrix,
)
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
NOW = datetime(2026, 8, 3, 4, 30, tzinfo=timezone.utc)
SECRETS = {
    ("fixture-ci", "fixture-key-1"): b"fixture-ci-fault-attestation-secret-32-bytes",
    ("host-runner", "host-key-1"): b"linux-host-fault-attestation-secret-32-bytes",
    ("live-probe", "live-key-1"): b"live-runtime-fault-attestation-secret-32-bytes",
}
ISSUER_AUTHORITIES = {
    "fixture-ci": ("deterministic-fixture",),
    "host-runner": ("linux-host",),
    "live-probe": ("live-runtime",),
}


def _issuer(authority: str) -> tuple[str, str]:
    return {
        "deterministic-fixture": ("fixture-ci", "fixture-key-1"),
        "linux-host": ("host-runner", "host-key-1"),
        "live-runtime": ("live-probe", "live-key-1"),
    }[authority]


def _observation(
    scenario: RuntimeFaultScenario,
    *,
    status: str = "passed",
    outcome: str | None = None,
    revision: str = REVISION,
) -> RuntimeFaultObservation:
    evidence = hashlib.sha256(
        f"evidence:{scenario.scenario_id}:{status}".encode("utf-8")
    ).hexdigest()
    observed = (
        None
        if status == "blocked"
        else (scenario.expected_outcome if outcome is None else outcome)
    )
    observed_at = NOW.isoformat(timespec="microseconds")
    return RuntimeFaultObservation(
        observation_id=f"obs.{scenario.scenario_id}",
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=revision,
        authority=scenario.authority,
        status=status,
        observed_outcome=observed,
        observed_at=observed_at,
        evidence_sha256=evidence,
        detail_code=None if status == "passed" else f"observed.{status}",
        provenance=ContractProvenance(
            origin="tests.runtime-fault-attestations",
            source_revision=revision,
            created_at=observed_at,
            input_digests=tuple(sorted((scenario.digest, evidence))),
        ),
    )


def _matrix(observations):
    return build_runtime_fault_matrix(
        matrix_id="gate0-runtime-faults-attested",
        source_revision=REVISION,
        observations=tuple(observations),
        generated_at=NOW.isoformat(timespec="microseconds"),
        catalog=RUNTIME_FAULT_CATALOG,
        provenance_origin="tests.runtime-fault-attested-matrix",
    )


def _attestation(
    observation: RuntimeFaultObservation,
    *,
    index: int = 0,
    issuer_id: str | None = None,
    key_id: str | None = None,
    secret: bytes | None = None,
    issued_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> RuntimeFaultAttestation:
    default_issuer, default_key = _issuer(observation.authority)
    chosen_issuer = issuer_id or default_issuer
    chosen_key = key_id or default_key
    chosen_secret = secret or SECRETS[(chosen_issuer, chosen_key)]
    return issue_runtime_fault_attestation(
        observation,
        catalog=RUNTIME_FAULT_CATALOG,
        attestation_id=f"att.{index}.{observation.scenario_id}",
        issuer_id=chosen_issuer,
        key_id=chosen_key,
        nonce=f"nonce.{index}.{observation.scenario_id}",
        issued_at=issued_at,
        expires_at=expires_at or (issued_at + timedelta(hours=1)),
        secret=chosen_secret,
    )


def _verify_one(
    attestation: RuntimeFaultAttestation,
    observation: RuntimeFaultObservation,
    *,
    now: datetime = NOW + timedelta(minutes=1),
    revision: str = REVISION,
    keyring=SECRETS,
    issuer_authorities=ISSUER_AUTHORITIES,
) -> str:
    return verify_runtime_fault_attestation(
        attestation,
        observation=observation,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=revision,
        keyring=keyring,
        issuer_authorities=issuer_authorities,
        now=now,
    )


def test_attestation_round_trip_signature_and_exact_binding() -> None:
    observation = _observation(RUNTIME_FAULT_CATALOG.scenarios[0])
    attestation = _attestation(observation)

    assert RuntimeFaultAttestation.from_dict(attestation.to_dict()) == attestation
    assert attestation.signature_sha256 != "0" * 64
    assert _verify_one(attestation, observation) == observation.digest


def test_complete_matrix_closes_only_through_authorized_attestations() -> None:
    observations = [_observation(row) for row in RUNTIME_FAULT_CATALOG.scenarios]
    matrix = _matrix(observations)
    attestations = [_attestation(row, index=index) for index, row in enumerate(observations)]

    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=tuple(reversed(attestations)),
        keyring=SECRETS,
        issuer_authorities=ISSUER_AUTHORITIES,
        now=NOW + timedelta(minutes=1),
    )

    assert verification.closed is True
    assert verification.blockers == ()
    assert verification.trusted_observation_sha256s == tuple(
        sorted(row.digest for row in observations)
    )


def test_missing_attestation_remains_an_untrusted_observation_blocker() -> None:
    observations = [_observation(row) for row in RUNTIME_FAULT_CATALOG.scenarios]
    attestations = [
        _attestation(row, index=index)
        for index, row in enumerate(observations[:-1])
    ]

    verification = verify_attested_runtime_fault_matrix(
        _matrix(observations),
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=attestations,
        keyring=SECRETS,
        issuer_authorities=ISSUER_AUTHORITIES,
        now=NOW + timedelta(minutes=1),
    )

    assert verification.closed is False
    assert verification.blockers == (
        f"fault.untrusted-observation:{observations[-1].scenario_id}",
    )


def test_valid_attestation_cannot_hide_wrong_observed_outcome() -> None:
    target = RUNTIME_FAULT_CATALOG.scenarios[0]
    wrong = next(
        value
        for value in ("failed", "cancelled", "refused-before-start")
        if value != target.expected_outcome
    )
    observations = [
        _observation(row, outcome=wrong if row == target else None)
        for row in RUNTIME_FAULT_CATALOG.scenarios
    ]
    attestations = [_attestation(row, index=index) for index, row in enumerate(observations)]

    verification = verify_attested_runtime_fault_matrix(
        _matrix(observations),
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=attestations,
        keyring=SECRETS,
        issuer_authorities=ISSUER_AUTHORITIES,
        now=NOW + timedelta(minutes=1),
    )

    assert f"fault.outcome-mismatch:{target.scenario_id}" in verification.blockers
    assert verification.closed is False


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_valid_attestation_does_not_convert_nonpassing_status_to_success(status: str) -> None:
    target = RUNTIME_FAULT_CATALOG.scenarios[0]
    observations = [
        _observation(row, status=status if row == target else "passed")
        for row in RUNTIME_FAULT_CATALOG.scenarios
    ]
    attestations = [_attestation(row, index=index) for index, row in enumerate(observations)]

    verification = verify_attested_runtime_fault_matrix(
        _matrix(observations),
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=attestations,
        keyring=SECRETS,
        issuer_authorities=ISSUER_AUTHORITIES,
        now=NOW + timedelta(minutes=1),
    )

    assert f"fault.{status}:{target.scenario_id}" in verification.blockers
    assert verification.closed is False


def test_signature_tampering_unknown_key_and_candidate_key_are_refused() -> None:
    observation = _observation(RUNTIME_FAULT_CATALOG.scenarios[0])
    attestation = _attestation(observation)

    with pytest.raises(RuntimeFaultAttestationSignatureError, match="signature"):
        _verify_one(
            dataclasses.replace(attestation, signature_sha256="f" * 64),
            observation,
        )
    with pytest.raises(RuntimeFaultAttestationSignatureError, match="unknown"):
        _verify_one(attestation, observation, keyring={})

    candidate_secret = b"candidate-controlled-attestation-secret-material"
    forged = _attestation(
        observation,
        secret=candidate_secret,
    )
    with pytest.raises(RuntimeFaultAttestationSignatureError, match="signature"):
        _verify_one(forged, observation)


def test_issuer_cannot_cross_authority_classes() -> None:
    observation = next(
        _observation(row)
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.authority == "live-runtime"
    )
    attestation = _attestation(
        observation,
        issuer_id="fixture-ci",
        key_id="fixture-key-1",
        secret=SECRETS[("fixture-ci", "fixture-key-1")],
    )

    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="not authorized"):
        _verify_one(attestation, observation)


def test_observation_catalog_revision_and_authority_bindings_are_exact() -> None:
    first = _observation(RUNTIME_FAULT_CATALOG.scenarios[0])
    second = _observation(RUNTIME_FAULT_CATALOG.scenarios[1])
    attestation = _attestation(first)

    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="scenario_id"):
        _verify_one(attestation, second)
    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="source_revision"):
        _verify_one(attestation, first, revision=OTHER_REVISION)

    changed = dataclasses.replace(first, status="failed", detail_code="changed.status")
    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="observation_sha256"):
        _verify_one(attestation, changed)

    foreign_catalog = dataclasses.replace(
        RUNTIME_FAULT_CATALOG,
        catalog_id="foreign-runtime-faults",
    )
    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="catalog_sha256"):
        verify_runtime_fault_attestation(
            attestation,
            observation=first,
            catalog=foreign_catalog,
            expected_source_revision=REVISION,
            keyring=SECRETS,
            issuer_authorities=ISSUER_AUTHORITIES,
            now=NOW + timedelta(minutes=1),
        )


def test_future_expired_and_overlong_attestations_are_refused() -> None:
    observation = _observation(RUNTIME_FAULT_CATALOG.scenarios[0])
    attestation = _attestation(observation)

    with pytest.raises(RuntimeFaultAttestationExpired, match="not valid yet"):
        _verify_one(attestation, observation, now=NOW - timedelta(seconds=1))
    with pytest.raises(RuntimeFaultAttestationExpired, match="expired"):
        _verify_one(attestation, observation, now=NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="seven days"):
        _attestation(
            observation,
            expires_at=NOW + timedelta(days=7, seconds=1),
        )
    with pytest.raises(ValueError, match="after issued_at"):
        _attestation(observation, expires_at=NOW)


def test_duplicate_ids_nonces_scenarios_and_foreign_targets_refuse() -> None:
    observations = [_observation(row) for row in RUNTIME_FAULT_CATALOG.scenarios[:2]]
    matrix = _matrix(observations)
    first = _attestation(observations[0], index=0)
    second = _attestation(observations[1], index=1)

    with pytest.raises(RuntimeFaultAttestationReplay, match="duplicate.*id"):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=(first, dataclasses.replace(second, attestation_id=first.attestation_id)),
            keyring=SECRETS,
            issuer_authorities=ISSUER_AUTHORITIES,
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(RuntimeFaultAttestationReplay, match="nonce"):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=(
                first,
                dataclasses.replace(
                    second,
                    issuer_id=first.issuer_id,
                    key_id=first.key_id,
                    nonce=first.nonce,
                ),
            ),
            keyring=SECRETS,
            issuer_authorities=ISSUER_AUTHORITIES,
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(RuntimeFaultAttestationReplay, match="same scenario"):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=(first, dataclasses.replace(first, attestation_id="att.other", nonce="nonce.other")),
            keyring=SECRETS,
            issuer_authorities=ISSUER_AUTHORITIES,
            now=NOW + timedelta(minutes=1),
        )

    foreign = _observation(RUNTIME_FAULT_CATALOG.scenarios[2])
    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="absent"):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=(_attestation(foreign, index=2),),
            keyring=SECRETS,
            issuer_authorities=ISSUER_AUTHORITIES,
            now=NOW + timedelta(minutes=1),
        )


def test_weak_secret_malformed_wire_and_string_collections_refuse() -> None:
    observation = _observation(RUNTIME_FAULT_CATALOG.scenarios[0])
    with pytest.raises(ValueError, match="at least 32"):
        _attestation(observation, secret=b"weak")

    payload = _attestation(observation).to_dict()
    payload["extra"] = True
    with pytest.raises(ValueError, match="fields mismatch"):
        RuntimeFaultAttestation.from_dict(payload)

    with pytest.raises(ValueError, match="must be an array"):
        verify_attested_runtime_fault_matrix(
            _matrix((observation,)),
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations="not-an-array",  # type: ignore[arg-type]
            keyring=SECRETS,
            issuer_authorities=ISSUER_AUTHORITIES,
            now=NOW,
        )

    attestation = _attestation(observation)
    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="must be an array"):
        _verify_one(
            attestation,
            observation,
            issuer_authorities={"fixture-ci": "deterministic-fixture"},  # type: ignore[dict-item]
        )
