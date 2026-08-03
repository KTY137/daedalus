from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.runtimes.fault_attestations import (
    AttestedRuntimeFaultVerification,
    issue_runtime_fault_attestation,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.faults import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultObservation,
    build_runtime_fault_matrix,
)
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 4, 45, tzinfo=timezone.utc)
SECRET = b"fixture-ci-fault-attestation-secret-32-bytes"


def _observation() -> RuntimeFaultObservation:
    scenario = next(
        row
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.authority == "deterministic-fixture"
    )
    evidence = hashlib.sha256(b"attested-receipt-evidence").hexdigest()
    observed_at = NOW.isoformat(timespec="microseconds")
    return RuntimeFaultObservation(
        observation_id="obs.attested-runtime-receipt",
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=REVISION,
        authority=scenario.authority,
        status="passed",
        observed_outcome=scenario.expected_outcome,
        observed_at=observed_at,
        evidence_sha256=evidence,
        detail_code=None,
        provenance=ContractProvenance(
            origin="tests.attested-runtime-receipt",
            source_revision=REVISION,
            created_at=observed_at,
            input_digests=tuple(sorted((scenario.digest, evidence))),
        ),
    )


def test_verification_receipt_retains_exact_attestations_and_time() -> None:
    observation = _observation()
    matrix = build_runtime_fault_matrix(
        matrix_id="attested-runtime-receipt",
        source_revision=REVISION,
        observations=(observation,),
        generated_at=NOW.isoformat(timespec="microseconds"),
        catalog=RUNTIME_FAULT_CATALOG,
        provenance_origin="tests.attested-runtime-receipt-matrix",
    )
    attestation = issue_runtime_fault_attestation(
        observation,
        catalog=RUNTIME_FAULT_CATALOG,
        attestation_id="att.attested-runtime-receipt",
        issuer_id="fixture-ci",
        key_id="fixture-key-1",
        nonce="nonce.attested-runtime-receipt",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        secret=SECRET,
    )

    receipt = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=(attestation,),
        keyring={("fixture-ci", "fixture-key-1"): SECRET},
        issuer_authorities={"fixture-ci": ("deterministic-fixture",)},
        now=NOW + timedelta(minutes=1),
    )

    assert isinstance(receipt, AttestedRuntimeFaultVerification)
    assert receipt.attestation_sha256s == (attestation.digest,)
    assert receipt.verified_at == (NOW + timedelta(minutes=1)).isoformat(
        timespec="microseconds"
    )
    assert receipt.trusted_observation_sha256s == (observation.digest,)
    assert receipt.closed is False
    assert receipt.to_dict()["fault_verification"]["matrix_sha256"] == matrix.digest
    assert len(receipt.digest) == 64

    repeated = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=(attestation,),
        keyring={("fixture-ci", "fixture-key-1"): SECRET},
        issuer_authorities={"fixture-ci": ("deterministic-fixture",)},
        now=NOW + timedelta(minutes=1),
    )
    assert repeated == receipt
    assert repeated.digest == receipt.digest


def test_verification_receipt_refuses_ambiguous_attestation_projection() -> None:
    observation = _observation()
    matrix = build_runtime_fault_matrix(
        matrix_id="attested-runtime-receipt-invalid",
        source_revision=REVISION,
        observations=(observation,),
        generated_at=NOW.isoformat(timespec="microseconds"),
        catalog=RUNTIME_FAULT_CATALOG,
    )
    from daedalus.runtimes.faults import verify_runtime_fault_matrix

    fault_verification = verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        trusted_observation_digests=(observation.digest,),
    )

    with pytest.raises(ValueError, match="one-to-one"):
        AttestedRuntimeFaultVerification(
            fault_verification=fault_verification,
            attestation_sha256s=(),
            verified_at=NOW.isoformat(),
        )
    with pytest.raises(ValueError, match="unique"):
        AttestedRuntimeFaultVerification(
            fault_verification=dataclasses.replace(
                fault_verification,
                trusted_observation_sha256s=(observation.digest, observation.digest),
            ),
            attestation_sha256s=("f" * 64, "f" * 64),
            verified_at=NOW.isoformat(),
        )
