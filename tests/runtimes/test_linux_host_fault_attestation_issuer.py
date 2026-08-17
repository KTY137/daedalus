"""The attestation issuer is the only path from a retained row into a trust set.

Every test here answers one question: can a record that is not exactly what the
canonical catalog demands still acquire a signature? The answer must be no, and
the refusal must be named.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes import fault_attestations
from daedalus.runtimes.fault_attestation_issuer import (
    FaultAttestationIssuerError,
    FaultAttestationRefusal,
    LinuxHostFaultAttestationIssuer,
    build_matrix_from_run_directory,
    issue_run_directory,
    load_linux_host_fault_run,
)
from daedalus.runtimes.fault_attestations import (
    RuntimeFaultAttestationSignatureError,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    LinuxHostFaultEvidence,
    LinuxHostFaultRun,
)
from daedalus.runtimes.fault_matrix import RuntimeFaultObservation
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
OBSERVED = datetime(2026, 8, 3, 4, 30, tzinfo=timezone.utc)
ISSUED = OBSERVED + timedelta(minutes=5)
SECRET = b"linux-host-fault-attestation-secret-32-bytes"
FOREIGN_SECRET = b"a-different-linux-host-attestation-secret-32"
EVIDENCE_SCHEMA = "daedalus-linux-host-fault-evidence/1"

LINUX_SCENARIOS = tuple(
    row for row in RUNTIME_FAULT_CATALOG.scenarios if row.authority == "linux-host"
)


def _forge_run(
    scenario,
    *,
    status: str = "passed",
    outcome: str | None = None,
    detail_code: str | None = None,
    scenario_sha256: str | None = None,
    executor: str | None = None,
    revision: str = REVISION,
    raw: bytes = b"forged-raw-evidence",
) -> LinuxHostFaultRun:
    """Build one internally consistent artifact triple for an exact scenario.

    Internal consistency is the point: the record survives every existing
    binding check, so whatever the issuer refuses it refuses on catalog grounds.
    """

    sha = scenario_sha256 or scenario.digest
    observed = outcome if outcome is not None else scenario.expected_outcome
    if status == "blocked":
        observed = None
    if status == "passed":
        detail = None
    else:
        detail = detail_code or "forged-detail"
    stamp = OBSERVED.isoformat(timespec="microseconds")
    evidence = LinuxHostFaultEvidence(
        schema=EVIDENCE_SCHEMA,
        scenario_id=scenario.scenario_id,
        scenario_sha256=sha,
        source_revision=revision,
        executor=executor if executor is not None else scenario.executor,
        executor_sha256=hashlib.sha256(b"forged-executor").hexdigest(),
        started_at=stamp,
        finished_at=stamp,
        status=status,
        observed_outcome=observed,
        detail_code=detail,
        raw_evidence_sha256=hashlib.sha256(raw).hexdigest(),
        facts=(HostFaultFact("probe", "forged"),),
    )
    observation = RuntimeFaultObservation(
        observation_id="host-" + evidence.digest[:24],
        scenario_id=scenario.scenario_id,
        scenario_sha256=sha,
        source_revision=revision,
        authority="linux-host",
        status=status,
        observed_outcome=observed,
        observed_at=stamp,
        evidence_sha256=evidence.digest,
        detail_code=detail,
        provenance=ContractProvenance(
            origin="tests.linux-host-fault-attestation-issuer",
            source_revision=revision,
            created_at=stamp,
            input_digests=tuple(sorted((sha, evidence.digest))),
        ),
    )
    return LinuxHostFaultRun(
        evidence=evidence, observation=observation, raw_evidence=raw
    )


def _publish(directory: Path, run: LinuxHostFaultRun) -> None:
    prefix = run.observation.scenario_id
    (directory / f"{prefix}.evidence.json").write_text(
        canonical_json(run.evidence.to_dict()) + "\n", encoding="utf-8"
    )
    (directory / f"{prefix}.observation.json").write_text(
        canonical_json(run.observation.to_dict()) + "\n", encoding="utf-8"
    )
    (directory / f"{prefix}.raw").write_bytes(run.raw_evidence)


def _run_directory(tmp_path: Path, scenarios=LINUX_SCENARIOS, **kwargs) -> Path:
    directory = tmp_path / "run"
    directory.mkdir(exist_ok=True)
    for scenario in scenarios:
        _publish(directory, _forge_run(scenario, raw=b"raw-" + scenario.scenario_id.encode(), **kwargs))
    return directory


def _issuer(*, revision: str = REVISION, secret: bytes = SECRET) -> LinuxHostFaultAttestationIssuer:
    return LinuxHostFaultAttestationIssuer(
        issuer_id="host-runner",
        key_id="host-key-1",
        secret=secret,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=revision,
    )


def _verify(directory: Path, bundle, *, keyring=None, revision: str = REVISION):
    matrix = build_matrix_from_run_directory(
        directory, catalog=RUNTIME_FAULT_CATALOG, source_revision=revision
    )
    return verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=revision,
        attestations=bundle.attestations,
        keyring=keyring if keyring is not None else {("host-runner", "host-key-1"): SECRET},
        issuer_authorities={"host-runner": ("linux-host",)},
        now=ISSUED + timedelta(minutes=1),
    )


def test_valid_evidence_becomes_a_trusted_observation(tmp_path: Path) -> None:
    directory = _run_directory(tmp_path)
    bundle = issue_run_directory(
        directory, issuer=_issuer(), key_class="development", issued_at=ISSUED
    )

    assert bundle.complete is True
    assert bundle.refusals == ()
    assert len(bundle.attestations) == len(LINUX_SCENARIOS)

    verification = _verify(directory, bundle)
    assert not [row for row in verification.blockers if "untrusted-observation" in row]
    # Every Linux row passed in this fixture, so no Linux row blocks at all.
    assert not [
        row
        for row in verification.blockers
        if row.split(":", 1)[1] in {s.scenario_id for s in LINUX_SCENARIOS}
    ]
    assert len(verification.trusted_observation_sha256s) == len(LINUX_SCENARIOS)


def test_a_partial_catalog_leaves_the_absent_rows_missing_not_trusted(
    tmp_path: Path,
) -> None:
    subset = LINUX_SCENARIOS[:3]
    directory = _run_directory(tmp_path, scenarios=subset)
    bundle = issue_run_directory(
        directory, issuer=_issuer(), key_class="development", issued_at=ISSUED
    )
    assert len(bundle.attestations) == 3

    verification = _verify(directory, bundle)
    absent = {row.scenario_id for row in LINUX_SCENARIOS} - {
        row.scenario_id for row in subset
    }
    for scenario_id in absent:
        assert f"fault.missing:{scenario_id}" in verification.blockers
        assert f"fault.untrusted-observation:{scenario_id}" not in verification.blockers
    assert verification.closed is False


def test_a_forged_success_over_blocked_evidence_is_refused(tmp_path: Path) -> None:
    scenario = LINUX_SCENARIOS[0]
    directory = tmp_path / "run"
    directory.mkdir()
    run = _forge_run(scenario, status="blocked", detail_code="docker-cli-unavailable")
    _publish(directory, run)

    # A candidate rewrites only the observation to claim the scenario passed.
    payload = json.loads((directory / f"{scenario.scenario_id}.observation.json").read_text())
    payload["status"] = "passed"
    payload["observed_outcome"] = scenario.expected_outcome
    payload["detail_code"] = None
    (directory / f"{scenario.scenario_id}.observation.json").write_text(
        canonical_json(payload) + "\n", encoding="utf-8"
    )

    with pytest.raises(FaultAttestationRefusal) as excinfo:
        load_linux_host_fault_run(directory, scenario.scenario_id)
    assert excinfo.value.reason == "refusal.run-binding-mismatch"

    bundle = issue_run_directory(
        directory, issuer=_issuer(), key_class="development", issued_at=ISSUED
    )
    assert bundle.attestations == ()
    assert bundle.complete is False
    assert bundle.refusals[0].reason == "refusal.run-binding-mismatch"


def test_tampered_raw_evidence_is_refused(tmp_path: Path) -> None:
    scenario = LINUX_SCENARIOS[0]
    directory = _run_directory(tmp_path, scenarios=(scenario,))
    (directory / f"{scenario.scenario_id}.raw").write_bytes(b"substituted-bytes")

    with pytest.raises(FaultAttestationRefusal) as excinfo:
        load_linux_host_fault_run(directory, scenario.scenario_id)
    assert excinfo.value.reason == "refusal.run-binding-mismatch"


def test_scenario_drift_is_refused_even_when_the_triple_is_consistent(
    tmp_path: Path,
) -> None:
    scenario = LINUX_SCENARIOS[0]
    other = LINUX_SCENARIOS[1]
    run = _forge_run(scenario, scenario_sha256=other.digest)
    directory = tmp_path / "run"
    directory.mkdir()
    _publish(directory, run)

    # The triple binds cleanly to itself; only the catalog exposes the drift.
    assert load_linux_host_fault_run(directory, scenario.scenario_id) == run
    with pytest.raises(FaultAttestationRefusal) as excinfo:
        _issuer().issue(run, issued_at=ISSUED)
    assert excinfo.value.reason == "refusal.scenario-drift"


def test_executor_drift_is_refused(tmp_path: Path) -> None:
    run = _forge_run(LINUX_SCENARIOS[0], executor="host-fixture:something-else")
    with pytest.raises(FaultAttestationRefusal) as excinfo:
        _issuer().issue(run, issued_at=ISSUED)
    assert excinfo.value.reason == "refusal.executor-drift"


def test_the_wrong_revision_is_refused(tmp_path: Path) -> None:
    directory = _run_directory(tmp_path, revision=OTHER_REVISION)
    bundle = issue_run_directory(
        directory,
        issuer=_issuer(revision=REVISION),
        key_class="development",
        issued_at=ISSUED,
    )

    assert bundle.attestations == ()
    assert len(bundle.refusals) == len(LINUX_SCENARIOS)
    assert {row.reason for row in bundle.refusals} == {"refusal.stale-revision"}


def test_an_outcome_contradicting_the_catalog_is_never_signed() -> None:
    scenario = next(
        row for row in LINUX_SCENARIOS if row.expected_outcome != "cancelled"
    )
    run = _forge_run(scenario, status="passed", outcome="cancelled")
    with pytest.raises(FaultAttestationRefusal) as excinfo:
        _issuer().issue(run, issued_at=ISSUED)
    assert excinfo.value.reason == "refusal.outcome-contradicts-catalog"


def test_a_failed_row_is_attested_but_still_blocks(tmp_path: Path) -> None:
    scenario = LINUX_SCENARIOS[0]
    directory = tmp_path / "run"
    directory.mkdir()
    _publish(
        directory,
        _forge_run(scenario, status="failed", outcome="failed", detail_code="executor-error"),
    )
    bundle = issue_run_directory(
        directory, issuer=_issuer(), key_class="development", issued_at=ISSUED
    )

    assert bundle.complete is True
    assert len(bundle.attestations) == 1

    verification = _verify(directory, bundle)
    # Authenticity was granted; the verdict is unchanged.
    assert f"fault.untrusted-observation:{scenario.scenario_id}" not in verification.blockers
    assert f"fault.failed:{scenario.scenario_id}" in verification.blockers


def test_an_attestation_predating_its_observation_is_refused() -> None:
    run = _forge_run(LINUX_SCENARIOS[0])
    with pytest.raises(FaultAttestationRefusal) as excinfo:
        _issuer().issue(run, issued_at=OBSERVED - timedelta(seconds=1))
    assert excinfo.value.reason == "refusal.attestation-predates-observation"


def test_a_foreign_key_cannot_verify(tmp_path: Path) -> None:
    directory = _run_directory(tmp_path, scenarios=LINUX_SCENARIOS[:1])
    bundle = issue_run_directory(
        directory,
        issuer=_issuer(secret=FOREIGN_SECRET),
        key_class="development",
        issued_at=ISSUED,
    )
    assert len(bundle.attestations) == 1

    with pytest.raises(RuntimeFaultAttestationSignatureError):
        _verify(directory, bundle, keyring={("host-runner", "host-key-1"): SECRET})


def test_the_signature_check_is_load_bearing(tmp_path: Path, monkeypatch) -> None:
    """Mutation probe: disable the signature comparison and this suite goes red.

    ``test_a_foreign_key_cannot_verify`` is only meaningful if the HMAC compare
    is what rejects the foreign key. Neutralise that one call and the refusal
    must disappear -- which proves the guard, not the surrounding bindings, is
    doing the work.
    """

    directory = _run_directory(tmp_path, scenarios=LINUX_SCENARIOS[:1])
    bundle = issue_run_directory(
        directory,
        issuer=_issuer(secret=FOREIGN_SECRET),
        key_class="development",
        issued_at=ISSUED,
    )

    with pytest.raises(RuntimeFaultAttestationSignatureError):
        _verify(directory, bundle, keyring={("host-runner", "host-key-1"): SECRET})

    monkeypatch.setattr(
        fault_attestations.hmac, "compare_digest", lambda left, right: True
    )
    neutralised = _verify(directory, bundle, keyring={("host-runner", "host-key-1"): SECRET})
    assert neutralised.trusted_observation_sha256s != ()


def test_the_issuer_is_out_of_driver_reach() -> None:
    """Invariant 3: producing evidence must not be a way to produce trust."""

    driver = Path(__file__).resolve().parents[2] / "daedalus" / "runtimes"
    for name in ("container_fault_driver.py", "host_fault_runner.py"):
        source = (driver / name).read_text(encoding="utf-8")
        assert "fault_attestation_issuer" not in source, name


def test_no_signing_key_is_embedded_in_the_issuer(monkeypatch) -> None:
    from daedalus.runtimes import fault_attestation_issuer

    monkeypatch.delenv("DAEDALUS_TEST_FAULT_KEY", raising=False)
    with pytest.raises(FaultAttestationIssuerError, match="unset or empty"):
        fault_attestation_issuer._secret_from_env("DAEDALUS_TEST_FAULT_KEY")

    monkeypatch.setenv("DAEDALUS_TEST_FAULT_KEY", "short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        fault_attestation_issuer._secret_from_env("DAEDALUS_TEST_FAULT_KEY")


def test_a_bundle_cannot_mix_issuers_or_revisions(tmp_path: Path) -> None:
    directory = _run_directory(tmp_path, scenarios=LINUX_SCENARIOS[:2])
    bundle = issue_run_directory(
        directory, issuer=_issuer(), key_class="development", issued_at=ISSUED
    )
    payload = bundle.to_dict()
    assert payload["key_class"] == "development"
    assert payload["key_sha256"] == hashlib.sha256(SECRET).hexdigest()
    assert hmac.compare_digest(payload["source_revision"], REVISION)

    import dataclasses

    with pytest.raises(ValueError, match="exact issuer identity"):
        dataclasses.replace(bundle, issuer_id="someone-else")
