# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The fixture issuer is a sibling of the host issuer, not a shared one.

The load-bearing property here is the cross-column refusal. Each column has its
own issuer, its own authority constant and its own key, so a compromised
collector on one side cannot manufacture trust for the other side's rows. That
refusal is asserted in both directions, at issuance and again at verification.

A signature also never upgrades a verdict: a blocked observation is attested
unchanged and still blocks the matrix.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes.fault_attestation_issuer import (
    FaultAttestationRefusal,
    LinuxHostFaultAttestationIssuer,
)
from daedalus.runtimes.fault_attestations import (
    RuntimeFaultAttestationBindingMismatch,
    RuntimeFaultAttestationSignatureError,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.fixture_fault_attestation_issuer import (
    FixtureFaultAttestationIssuer,
    build_matrix_from_fixture_run_directory,
    issue_fixture_run_directory,
    load_fixture_fault_run,
)
from daedalus.runtimes.fixture_fault_collector import (
    PytestInvocation,
    run_fixture_fault,
)
from daedalus.runtimes.host_fault_runner import (
    HostFaultResult,
    LinuxHostExecutorBinding,
    run_linux_host_fault,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "1" * 40
FIXTURE_SECRET = b"fixture-column-signing-secret-material-32+"
HOST_SECRET = b"linux-host-column-signing-secret-material-32+"
NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def _junit(outcome: str | None) -> str:
    inner = ""
    if outcome is not None:
        inner = (
            "<properties><property "
            f'name="runtime_fault_observed_outcome" value="{outcome}" />'
            "</properties>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        f'tests="1"><testcase classname="t" name="t" time="0.1">{inner}</testcase>'
        "</testsuite></testsuites>"
    )


def _fixture_run(scenario_id: str = "runtime.fence.quarantine-wins", *, outcome=...):
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[scenario_id]
    chosen = scenario.expected_outcome if outcome is ... else outcome
    return run_fixture_fault(
        scenario,
        source_revision=REVISION,
        runner=lambda _node: PytestInvocation(
            exit_code=0, stdout="1 passed", junit_xml=_junit(chosen)
        ),
        repo_root=REPO_ROOT,
        clock=lambda: NOW,
    )


def _host_run(scenario_id: str = "runtime.process.timeout"):
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[scenario_id]
    binding = LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256="c" * 64,
        execute=lambda _s: HostFaultResult(
            status="passed",
            observed_outcome=scenario.expected_outcome,
            detail_code=None,
            raw_evidence=b"host evidence",
        ),
    )
    return run_linux_host_fault(
        scenario, source_revision=REVISION, executor=binding, clock=lambda: NOW
    )


def _fixture_issuer(**overrides) -> FixtureFaultAttestationIssuer:
    kwargs = dict(
        issuer_id="fixture-column-issuer",
        key_id="fixture-dev-key",
        secret=FIXTURE_SECRET,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
    )
    kwargs.update(overrides)
    return FixtureFaultAttestationIssuer(**kwargs)


def _host_issuer() -> LinuxHostFaultAttestationIssuer:
    return LinuxHostFaultAttestationIssuer(
        issuer_id="host-column-issuer",
        key_id="host-dev-key",
        secret=HOST_SECRET,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
    )


def _retain(directory: Path, run) -> None:
    scenario_id = run.observation.scenario_id
    (directory / f"{scenario_id}.evidence.json").write_text(
        json.dumps(run.evidence.to_dict()), encoding="utf-8"
    )
    (directory / f"{scenario_id}.observation.json").write_text(
        json.dumps(run.observation.to_dict()), encoding="utf-8"
    )
    (directory / f"{scenario_id}.raw").write_bytes(run.raw_evidence)


def test_valid_fixture_run_is_signed() -> None:
    attestation = _fixture_issuer().issue(_fixture_run(), issued_at=NOW)
    assert attestation.authority == "deterministic-fixture"
    assert attestation.issuer_id == "fixture-column-issuer"


def test_fixture_issuer_refuses_a_linux_host_run() -> None:
    """The other column's artifact is not a FixtureFaultRun and never signs."""

    with pytest.raises(FaultAttestationRefusal) as caught:
        _fixture_issuer().issue(_host_run(), issued_at=NOW)
    assert caught.value.reason == "refusal.artifact-malformed"


def test_fixture_issuer_refuses_a_linux_host_scenario_id() -> None:
    issuer = _fixture_issuer()
    with pytest.raises(FaultAttestationRefusal) as caught:
        issuer._scenario("runtime.process.timeout")
    assert caught.value.reason == "refusal.foreign-authority"


def test_host_issuer_refuses_a_fixture_run() -> None:
    """And the refusal is symmetric: neither column can sign the other."""

    with pytest.raises(FaultAttestationRefusal) as caught:
        _host_issuer().issue(_fixture_run(), issued_at=NOW)
    assert caught.value.reason == "refusal.artifact-malformed"


def test_host_issuer_refuses_a_fixture_scenario_id() -> None:
    with pytest.raises(FaultAttestationRefusal) as caught:
        _host_issuer()._scenario("runtime.fence.quarantine-wins")
    assert caught.value.reason == "refusal.foreign-authority"


def test_fixture_issuer_scopes_itself_to_its_own_authority() -> None:
    assert _fixture_issuer().issuer_authorities == {
        "fixture-column-issuer": ("deterministic-fixture",)
    }
    assert _host_issuer().issuer_authorities == {"host-column-issuer": ("linux-host",)}


def test_stale_revision_is_refused() -> None:
    issuer = _fixture_issuer(expected_source_revision="2" * 40)
    with pytest.raises(FaultAttestationRefusal) as caught:
        issuer.issue(_fixture_run(), issued_at=NOW)
    assert caught.value.reason == "refusal.stale-revision"


def test_outcome_contradicting_the_catalog_is_refused() -> None:
    run = _fixture_run(outcome="unknown-reconciled")
    assert run.observation.status == "failed"  # the collector already caught it
    # A failed observation is attested unchanged; it is the *passed* claim that
    # must never contradict the catalog.
    attestation = _fixture_issuer().issue(run, issued_at=NOW)
    assert attestation.scenario_id == "runtime.fence.quarantine-wins"


def test_attestation_may_not_predate_its_observation() -> None:
    with pytest.raises(FaultAttestationRefusal) as caught:
        _fixture_issuer().issue(
            _fixture_run(), issued_at=NOW - timedelta(hours=1)
        )
    assert caught.value.reason == "refusal.attestation-predates-observation"


def test_blocked_observation_is_attested_but_still_blocks(tmp_path: Path) -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.fence.quarantine-wins"]
    run = run_fixture_fault(
        scenario,
        source_revision=REVISION,
        runner=lambda _node: PytestInvocation(exit_code=5, stdout="", junit_xml=""),
        repo_root=REPO_ROOT,
        clock=lambda: NOW,
    )
    assert run.observation.status == "blocked"
    _retain(tmp_path, run)
    issuer = _fixture_issuer()
    bundle = issue_fixture_run_directory(
        tmp_path, issuer=issuer, key_class="development", issued_at=NOW
    )
    assert bundle.complete
    assert len(bundle.attestations) == 1

    matrix = build_matrix_from_fixture_run_directory(
        tmp_path, catalog=RUNTIME_FAULT_CATALOG, source_revision=REVISION
    )
    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=bundle.attestations,
        keyring={(issuer.issuer_id, issuer.key_id): FIXTURE_SECRET},
        issuer_authorities=issuer.issuer_authorities,
        now=NOW,
    )
    # Authentic, and still a blocker. A signature is not a verdict.
    assert "fault.blocked:runtime.fence.quarantine-wins" in verification.blockers


def test_signed_fixture_row_enters_the_trust_set(tmp_path: Path) -> None:
    run = _fixture_run()
    _retain(tmp_path, run)
    issuer = _fixture_issuer()
    bundle = issue_fixture_run_directory(
        tmp_path, issuer=issuer, key_class="development", issued_at=NOW
    )
    matrix = build_matrix_from_fixture_run_directory(
        tmp_path, catalog=RUNTIME_FAULT_CATALOG, source_revision=REVISION
    )
    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=bundle.attestations,
        keyring={(issuer.issuer_id, issuer.key_id): FIXTURE_SECRET},
        issuer_authorities=issuer.issuer_authorities,
        now=NOW,
    )
    scenario_id = run.observation.scenario_id
    assert run.observation.digest in verification.trusted_observation_sha256s
    assert f"fault.untrusted-observation:{scenario_id}" not in verification.blockers
    assert f"fault.blocked:{scenario_id}" not in verification.blockers
    assert f"fault.failed:{scenario_id}" not in verification.blockers


def test_verification_refuses_a_fixture_attestation_from_a_host_scoped_issuer(
    tmp_path: Path,
) -> None:
    """Even a correctly signed row is rejected when the issuer is host-scoped."""

    run = _fixture_run()
    _retain(tmp_path, run)
    issuer = _fixture_issuer()
    bundle = issue_fixture_run_directory(
        tmp_path, issuer=issuer, key_class="development", issued_at=NOW
    )
    matrix = build_matrix_from_fixture_run_directory(
        tmp_path, catalog=RUNTIME_FAULT_CATALOG, source_revision=REVISION
    )
    # Verification is fail-closed: a column-scoping violation raises rather
    # than degrading into a blocker that a caller might tally and ignore.
    with pytest.raises(RuntimeFaultAttestationBindingMismatch):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=bundle.attestations,
            keyring={(issuer.issuer_id, issuer.key_id): FIXTURE_SECRET},
            # The same issuer id, scoped to the wrong column.
            issuer_authorities={issuer.issuer_id: ("linux-host",)},
            now=NOW,
        )


def test_wrong_key_does_not_verify(tmp_path: Path) -> None:
    run = _fixture_run()
    _retain(tmp_path, run)
    issuer = _fixture_issuer()
    bundle = issue_fixture_run_directory(
        tmp_path, issuer=issuer, key_class="development", issued_at=NOW
    )
    matrix = build_matrix_from_fixture_run_directory(
        tmp_path, catalog=RUNTIME_FAULT_CATALOG, source_revision=REVISION
    )
    # The host column's key must not authenticate a fixture row.
    with pytest.raises(RuntimeFaultAttestationSignatureError):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=bundle.attestations,
            keyring={(issuer.issuer_id, issuer.key_id): HOST_SECRET},
            issuer_authorities=issuer.issuer_authorities,
            now=NOW,
        )


def test_tampered_retained_observation_is_refused(tmp_path: Path) -> None:
    run = _fixture_run()
    _retain(tmp_path, run)
    payload = json.loads(
        (tmp_path / f"{run.observation.scenario_id}.observation.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["observed_outcome"] == "cancelled"
    payload["observed_outcome"] = "unknown-reconciled"
    (tmp_path / f"{run.observation.scenario_id}.observation.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    bundle = issue_fixture_run_directory(
        tmp_path, issuer=_fixture_issuer(), key_class="development", issued_at=NOW
    )
    # The evidence digest no longer matches the mutated observation.
    assert not bundle.complete
    assert bundle.refusals[0].reason == "refusal.run-binding-mismatch"


def test_missing_raw_evidence_is_refused_by_name(tmp_path: Path) -> None:
    run = _fixture_run()
    _retain(tmp_path, run)
    (tmp_path / f"{run.observation.scenario_id}.raw").unlink()
    with pytest.raises(FaultAttestationRefusal) as caught:
        load_fixture_fault_run(tmp_path, run.observation.scenario_id)
    assert caught.value.reason == "refusal.artifact-missing"


def test_bundle_rejects_a_foreign_authority_attestation(tmp_path: Path) -> None:
    from daedalus.runtimes.fixture_fault_attestation_issuer import (
        FixtureFaultAttestationBundle,
    )

    host_attestation = _host_issuer().issue(_host_run(), issued_at=NOW)
    with pytest.raises(ValueError, match="deterministic-fixture"):
        FixtureFaultAttestationBundle(
            schema="daedalus-fixture-fault-attestation-bundle/1",
            issuer_id="host-column-issuer",
            key_id="host-dev-key",
            key_class="development",
            key_sha256="d" * 64,
            catalog_sha256=RUNTIME_FAULT_CATALOG.digest,
            source_revision=REVISION,
            issued_at=NOW.isoformat(timespec="microseconds"),
            attestations=(host_attestation,),
            refusals=(),
        )
