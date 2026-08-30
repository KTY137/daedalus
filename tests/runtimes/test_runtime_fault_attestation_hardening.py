# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.runtimes.fault_attestations import (
    RuntimeFaultAttestation,
    RuntimeFaultAttestationBindingMismatch,
    RuntimeFaultAttestationSignatureError,
    issue_runtime_fault_attestation,
    verify_runtime_fault_attestation,
)
from daedalus.runtimes.faults import RUNTIME_FAULT_CATALOG, RuntimeFaultObservation
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json

REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 4, 30, tzinfo=timezone.utc)
SECRET = b"fixture-ci-fault-attestation-secret-32-bytes"
KEYRING = {("fixture-ci", "fixture-key-1"): SECRET}
POLICY = {"fixture-ci": ("deterministic-fixture",)}


def _observation() -> RuntimeFaultObservation:
    scenario = next(
        row
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.authority == "deterministic-fixture"
    )
    evidence = hashlib.sha256(b"hardening-evidence").hexdigest()
    observed_at = NOW.isoformat(timespec="microseconds")
    return RuntimeFaultObservation(
        observation_id="obs.runtime-attestation-hardening",
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
            origin="tests.runtime-fault-attestation-hardening",
            source_revision=REVISION,
            created_at=observed_at,
            input_digests=tuple(sorted((scenario.digest, evidence))),
        ),
    )


def _issue(observation: RuntimeFaultObservation, *, issued_at: datetime = NOW):
    return issue_runtime_fault_attestation(
        observation,
        catalog=RUNTIME_FAULT_CATALOG,
        attestation_id="att.runtime-attestation-hardening",
        issuer_id="fixture-ci",
        key_id="fixture-key-1",
        nonce="nonce.runtime-attestation-hardening",
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=1),
        secret=SECRET,
    )


def _verify(attestation: RuntimeFaultAttestation, observation: RuntimeFaultObservation):
    return verify_runtime_fault_attestation(
        attestation,
        observation=observation,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        keyring=KEYRING,
        issuer_authorities=POLICY,
        now=NOW + timedelta(minutes=1),
    )


def test_attestation_schema_is_explicit_and_strict() -> None:
    observation = _observation()
    payload = _issue(observation).to_dict()
    assert payload["schema"] == "daedalus-runtime-fault-attestation/1"

    payload["schema"] = "daedalus-runtime-fault-attestation/0"
    with pytest.raises(ValueError, match="schema must be"):
        RuntimeFaultAttestation.from_dict(payload)


def test_hmac_is_domain_separated_from_raw_canonical_json() -> None:
    observation = _observation()
    attestation = _issue(observation)
    legacy_signature = hmac.new(
        SECRET,
        canonical_json(attestation.signing_payload()).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert legacy_signature != attestation.signature_sha256

    with pytest.raises(RuntimeFaultAttestationSignatureError, match="signature"):
        _verify(
            dataclasses.replace(attestation, signature_sha256=legacy_signature),
            observation,
        )


def test_attestation_cannot_predate_the_retained_observation() -> None:
    observation = _observation()
    predating = _issue(observation, issued_at=NOW - timedelta(seconds=1))

    with pytest.raises(RuntimeFaultAttestationBindingMismatch, match="predates"):
        _verify(predating, observation)

    assert _verify(_issue(observation, issued_at=NOW), observation) == observation.digest
