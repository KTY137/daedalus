from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.runtimes.fault_matrix import (
    RUNTIME_FAULT_CATALOG,
    build_runtime_fault_matrix,
    verify_runtime_fault_matrix,
)
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultBindingMismatch,
    LinuxHostFaultClockError,
    LinuxHostFaultEvidence,
    LinuxHostFaultRun,
    load_linux_host_fault_evidence_json,
    run_linux_host_fault,
    run_linux_host_fault_catalog,
)

REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 4, 30, tzinfo=timezone.utc)


class StepClock:
    def __init__(self, *values: datetime):
        self._values = iter(values)

    def __call__(self) -> datetime:
        return next(self._values)


def scenario(scenario_id: str = "runtime.process.timeout"):
    return RUNTIME_FAULT_CATALOG.scenario_map[scenario_id]


def passing_result(row=None) -> HostFaultResult:
    row = row or scenario()
    return HostFaultResult(
        status="passed",
        observed_outcome=row.expected_outcome,
        detail_code=None,
        raw_evidence=b'{"exit_code":124,"process_group_empty":true}',
        facts=(
            HostFaultFact("exit-code", "124"),
            HostFaultFact("process-group-empty", "true"),
        ),
    )


def binding(row=None, execute=passing_result, *, locator: str | None = None):
    row = row or scenario()
    return LinuxHostExecutorBinding(
        locator=locator or row.executor,
        implementation_sha256="f" * 64,
        execute=execute,
    )


def test_pass_run_binds_exact_scenario_evidence_and_provenance() -> None:
    row = scenario()
    run = run_linux_host_fault(
        row,
        source_revision=REVISION,
        executor=binding(),
        clock=StepClock(NOW, NOW + timedelta(seconds=2)),
    )

    assert run.evidence.scenario_id == row.scenario_id
    assert run.evidence.scenario_sha256 == row.digest
    assert run.evidence.executor == row.executor
    assert run.evidence.executor_sha256 == "f" * 64
    assert run.evidence.status == "passed"
    assert run.observation.evidence_sha256 == run.evidence.digest
    assert run.observation.provenance.input_digests == tuple(
        sorted((row.digest, run.evidence.digest))
    )
    assert LinuxHostFaultRun(run.evidence, run.observation, run.raw_evidence) == run


def test_missing_executors_are_explicit_blockers_and_cannot_close_matrix() -> None:
    linux_rows = tuple(
        row for row in RUNTIME_FAULT_CATALOG.scenarios if row.authority == "linux-host"
    )
    values = []
    current = NOW
    for _ in linux_rows:
        values.extend((current, current + timedelta(milliseconds=1)))
        current += timedelta(seconds=1)

    runs = run_linux_host_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=REVISION,
        executors={},
        clock=StepClock(*values),
    )
    assert len(runs) == len(linux_rows) == 9
    assert all(run.observation.status == "blocked" for run in runs)
    assert all(run.observation.detail_code == "executor-unavailable" for run in runs)

    matrix = build_runtime_fault_matrix(
        matrix_id="linux-host-partial",
        source_revision=REVISION,
        observations=tuple(run.observation for run in runs),
        generated_at=(current + timedelta(seconds=1)).isoformat(),
        catalog=RUNTIME_FAULT_CATALOG,
        provenance_origin="tests.linux-host-runner",
    )
    verification = verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        trusted_observation_digests=tuple(run.observation.digest for run in runs),
    )
    assert not verification.closed
    assert "fault.blocked:runtime.process.timeout" in verification.blockers
    assert "fault.missing:runtime.live-envelope.expiry" in verification.blockers


def test_reported_pass_with_wrong_outcome_is_downgraded_to_failed() -> None:
    row = scenario()

    def wrong(_):
        return dataclasses.replace(
            passing_result(row),
            observed_outcome="failed",
        )

    run = run_linux_host_fault(
        row,
        source_revision=REVISION,
        executor=binding(execute=wrong),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    assert run.observation.status == "failed"
    assert run.observation.observed_outcome == "failed"
    assert run.observation.detail_code == "outcome-mismatch"
    assert {fact.name: fact.value for fact in run.evidence.facts}[
        "collector-expected-outcome"
    ] == row.expected_outcome


def test_executor_exception_is_sanitized_and_does_not_retain_message() -> None:
    def explode(_):
        raise RuntimeError("token=SUPER-SECRET")

    run = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(execute=explode),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    wire = str(run.to_dict())
    assert run.observation.status == "failed"
    assert run.observation.detail_code == "executor-error"
    assert "RuntimeError" in wire
    assert "SUPER-SECRET" not in wire


def test_non_result_executor_value_fails_closed() -> None:
    run = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(execute=lambda _: {"status": "passed"}),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    assert run.observation.status == "failed"
    assert run.observation.detail_code == "executor-contract"


def test_foreign_authority_and_foreign_executor_registration_refuse() -> None:
    deterministic = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.broker.exact-replay-inert"
    ]
    with pytest.raises(LinuxHostFaultBindingMismatch, match="not a linux-host"):
        run_linux_host_fault(
            deterministic,
            source_revision=REVISION,
            executor=None,
            clock=StepClock(NOW, NOW),
        )

    with pytest.raises(LinuxHostFaultBindingMismatch, match="foreign locators"):
        run_linux_host_fault_catalog(
            catalog=RUNTIME_FAULT_CATALOG,
            source_revision=REVISION,
            executors={
                "host-fixture:not-in-catalog": binding(
                    locator="host-fixture:not-in-catalog"
                )
            },
            clock=StepClock(NOW, NOW),
        )

    row = scenario()
    with pytest.raises(LinuxHostFaultBindingMismatch, match="registry key"):
        run_linux_host_fault_catalog(
            catalog=RUNTIME_FAULT_CATALOG,
            source_revision=REVISION,
            executors={row.executor: binding(row, locator="host-fixture:other")},
            clock=StepClock(NOW, NOW),
        )


def test_evidence_strict_round_trip_and_repacking_refuse() -> None:
    run = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    assert LinuxHostFaultEvidence.from_dict(run.evidence.to_dict()) == run.evidence
    wire = json.dumps(run.evidence.to_dict(), sort_keys=True)
    assert load_linux_host_fault_evidence_json(wire) == run.evidence

    duplicate_json = wire.replace(
        '"schema": "daedalus-linux-host-fault-evidence/1"',
        '"schema": "daedalus-linux-host-fault-evidence/1", '
        '"schema": "daedalus-linux-host-fault-evidence/1"',
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_linux_host_fault_evidence_json(duplicate_json)
    with pytest.raises(ValueError, match="non-finite"):
        load_linux_host_fault_evidence_json('{"value": NaN}')

    duplicate = run.evidence.to_dict()
    duplicate["facts"] = [
        {"name": "same", "value": "one"},
        {"name": "same", "value": "two"},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        LinuxHostFaultEvidence.from_dict(duplicate)

    extra = run.evidence.to_dict()
    extra["trusted"] = True
    with pytest.raises(ValueError, match="extra"):
        LinuxHostFaultEvidence.from_dict(extra)

    with pytest.raises(ValueError, match="HostFaultFact"):
        HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="malformed-fact",
            raw_evidence=b"x",
            facts=({"name": "not-a-record", "value": "x"},),
        )

    with pytest.raises(LinuxHostFaultBindingMismatch, match="raw evidence"):
        LinuxHostFaultRun(run.evidence, run.observation, b"substituted")


def test_same_inputs_and_clock_produce_same_content_identity() -> None:
    first = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    second = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    assert first.evidence.digest == second.evidence.digest
    assert first.observation.digest == second.observation.digest
    assert first.digest == second.digest


def test_clock_regression_and_naive_clock_refuse() -> None:
    with pytest.raises(LinuxHostFaultClockError, match="moved backwards"):
        run_linux_host_fault(
            scenario(),
            source_revision=REVISION,
            executor=binding(),
            clock=StepClock(NOW, NOW - timedelta(seconds=1)),
        )
    with pytest.raises(LinuxHostFaultClockError, match="timezone-aware"):
        run_linux_host_fault(
            scenario(),
            source_revision=REVISION,
            executor=binding(),
            clock=StepClock(datetime(2026, 8, 3), NOW),
        )


def test_result_contract_and_evidence_size_are_bounded() -> None:
    with pytest.raises(ValueError, match="require observed_outcome"):
        HostFaultResult(
            status="passed",
            observed_outcome=None,
            detail_code=None,
            raw_evidence=b"x",
        )
    with pytest.raises(ValueError, match="must not invent"):
        HostFaultResult(
            status="blocked",
            observed_outcome="failed",
            detail_code="blocked",
            raw_evidence=b"x",
        )
    with pytest.raises(ValueError, match="one MiB"):
        HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="too-large",
            raw_evidence=b"x" * (1024 * 1024 + 1),
        )


def test_stale_revision_remains_visible_to_canonical_verifier() -> None:
    row = scenario()
    run = run_linux_host_fault(
        row,
        source_revision=REVISION,
        executor=binding(),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    matrix = build_runtime_fault_matrix(
        matrix_id="stale-linux-host-run",
        source_revision=REVISION,
        observations=(run.observation,),
        generated_at=(NOW + timedelta(seconds=2)).isoformat(),
        catalog=RUNTIME_FAULT_CATALOG,
    )
    verification = verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision="b" * 40,
        trusted_observation_digests=(run.observation.digest,),
    )
    assert "fault.matrix-stale-revision" in verification.blockers
    assert "fault.stale-revision:runtime.process.timeout" in verification.blockers
