from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultBindingMismatch,
    LinuxHostFaultRun,
    run_linux_host_fault,
)

REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 5, 0, tzinfo=timezone.utc)


class StepClock:
    def __init__(self, *values: datetime):
        self._values = iter(values)

    def __call__(self) -> datetime:
        return next(self._values)


def scenario():
    return RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.timeout"]


def binding(execute, *, implementation_sha256: str = "f" * 64):
    return LinuxHostExecutorBinding(
        locator=scenario().executor,
        implementation_sha256=implementation_sha256,
        execute=execute,
    )


def passed(_):
    return HostFaultResult(
        status="passed",
        observed_outcome=scenario().expected_outcome,
        detail_code=None,
        raw_evidence=b'{"process_group_empty":true}',
    )


def test_control_flow_exceptions_are_not_laundered_into_fault_evidence() -> None:
    def interrupted(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_linux_host_fault(
            scenario(),
            source_revision=REVISION,
            executor=binding(interrupted),
            clock=StepClock(NOW),
        )


def test_executor_implementation_substitution_invalidates_the_run() -> None:
    run = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(passed),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    substituted = dataclasses.replace(
        run.evidence,
        executor_sha256="e" * 64,
    )
    with pytest.raises(LinuxHostFaultBindingMismatch, match="evidence_sha256"):
        LinuxHostFaultRun(substituted, run.observation, run.raw_evidence)


def test_executor_binding_locator_substitution_refuses_before_invocation() -> None:
    calls = []

    def record_call(_):
        calls.append("invoked")
        return passed(None)

    foreign = LinuxHostExecutorBinding(
        locator="host-fixture:foreign-timeout-runner",
        implementation_sha256="f" * 64,
        execute=record_call,
    )
    with pytest.raises(LinuxHostFaultBindingMismatch, match="locator"):
        run_linux_host_fault(
            scenario(),
            source_revision=REVISION,
            executor=foreign,
            clock=StepClock(NOW),
        )
    assert calls == []


def test_source_revision_changes_observation_and_evidence_identity() -> None:
    first = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(passed),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    second = run_linux_host_fault(
        scenario(),
        source_revision="b" * 40,
        executor=binding(passed),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    assert first.evidence.digest != second.evidence.digest
    assert first.observation.digest != second.observation.digest


def test_executor_implementation_identity_changes_evidence_identity() -> None:
    first = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(passed, implementation_sha256="f" * 64),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    second = run_linux_host_fault(
        scenario(),
        source_revision=REVISION,
        executor=binding(passed, implementation_sha256="e" * 64),
        clock=StepClock(NOW, NOW + timedelta(seconds=1)),
    )
    assert first.evidence.digest != second.evidence.digest
    assert first.observation.digest != second.observation.digest
