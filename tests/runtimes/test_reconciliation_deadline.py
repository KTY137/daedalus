# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Council CHECK (a): a reconciliation deadline for ``started-unreconciled``.

A durably STARTED effect whose external call already happened is retained for
reconciliation instead of being terminalized -- that is the honest shape. But
retention without a clock is a place where a debt can silently age out. This
test pins the guard: once the observation's evidence timestamp is older than
the declared deadline, the matrix carries exactly one
``fault.reconciliation-overdue`` blocker, while the durable STARTED row in the
real effect ledger is left untouched (no forced terminalization -- the council
itself corrected that in round 2).

The STARTED/no-terminal state is produced by the same machinery as the
canonical ``runtime.effect-terminal.disk-full`` scenario: the broker suffers an
I/O failure at terminal persistence, so the honest durable record is the
retained start.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.runtimes.faults import (
    RECONCILIATION_DEADLINE_SECONDS,
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultObservation,
    build_runtime_fault_matrix,
    verify_runtime_fault_matrix,
)
from daedalus.runtimes.fixture_fault_collector import derive_terminal_outcome
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
SCENARIO_ID = "runtime.effect-terminal.disk-full"
EVIDENCE_SHA = "d" * 64

_BROKER_TESTS = Path(__file__).resolve().parent / "test_runtime_provider_broker.py"


def _load_broker_test_module():
    """Load the broker fault tests as a module, the way they load their fixture."""

    name = "daedalus_council_checks_broker_module"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _BROKER_TESTS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _observation(observed_at: str) -> RuntimeFaultObservation:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[SCENARIO_ID]
    return RuntimeFaultObservation(
        observation_id="obs.council-reconciliation-deadline",
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=REVISION,
        authority=scenario.authority,
        status="passed",
        observed_outcome="started-unreconciled",
        observed_at=observed_at,
        evidence_sha256=EVIDENCE_SHA,
        detail_code=None,
        provenance=ContractProvenance(
            origin="tests.council-reconciliation-deadline",
            source_revision=REVISION,
            created_at=observed_at,
            input_digests=tuple(sorted((scenario.digest, EVIDENCE_SHA))),
        ),
    )


def test_overdue_unreconciled_start_blocks_matrix_and_leaves_ledger_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = _load_broker_test_module()

    # -- Produce the real durable STARTED/no-terminal state at T. --------------
    authorization, execution, authority, ledger = broker._subject(tmp_path, monkeypatch)

    def fail_finish(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        broker.RuntimeBoundEffectAuthorization, "finish_effect", fail_finish
    )
    with pytest.raises(broker.RuntimeProviderStateError, match="terminal receipt"):
        broker._run(authorization, execution, authority, ledger, invoke=lambda: "output")

    state, terminal_json = broker._durable_execution_row(tmp_path, execution.execution_id)
    assert state == "STARTED"
    assert terminal_json is None

    # The collector path names this exact shape, and only this exact shape.
    outcome = derive_terminal_outcome(
        terminal_outcome=None,
        execution_state=state,
        reconciliation_pending=True,
    )
    assert outcome == "started-unreconciled"

    # -- Record the observation at T and build the matrix. ---------------------
    observation_time = broker.fixture.NOW + timedelta(seconds=5)
    observed_at = observation_time.isoformat(timespec="microseconds")
    observation = _observation(observed_at)
    digest_before = observation.digest
    matrix = build_runtime_fault_matrix(
        matrix_id="council-reconciliation-deadline",
        source_revision=REVISION,
        observations=(observation,),
        generated_at=observed_at,
        catalog=RUNTIME_FAULT_CATALOG,
        provenance_origin="tests.council-reconciliation-deadline",
    )

    deadline = timedelta(seconds=RECONCILIATION_DEADLINE_SECONDS)

    # -- At exactly T + deadline the debt is not yet overdue. ------------------
    at_deadline = verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        trusted_observation_digests=(observation.digest,),
        now=observation_time + deadline,
    )
    assert not any(
        row.startswith("fault.reconciliation-overdue") for row in at_deadline.blockers
    )

    # -- One microsecond past the deadline it is exactly one overdue blocker. --
    overdue = verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        trusted_observation_digests=(observation.digest,),
        now=observation_time + deadline + timedelta(microseconds=1),
    )
    overdue_blockers = [
        row for row in overdue.blockers if row.startswith("fault.reconciliation-overdue")
    ]
    assert overdue_blockers == [f"fault.reconciliation-overdue:{SCENARIO_ID}"]
    assert overdue.closed is False
    # The overdue finding is its own blocker, not a re-labelling of the row's
    # otherwise clean verification: the scenario has no failed/blocked/mismatch
    # blocker, and every other blocker is a fault.missing for an unrelated row.
    assert not any(
        row.endswith(f":{SCENARIO_ID}")
        for row in overdue.blockers
        if not row.startswith("fault.reconciliation-overdue")
    )
    assert all(
        row.startswith("fault.missing:")
        for row in overdue.blockers
        if row not in overdue_blockers
    )

    # -- The guard never touches the durable STARTED state. --------------------
    state_after, terminal_after = broker._durable_execution_row(
        tmp_path, execution.execution_id
    )
    assert (state_after, terminal_after) == ("STARTED", None)
    assert observation.digest == digest_before
    assert observation.status == "passed"
    assert observation.observed_outcome == "started-unreconciled"


def test_reconciliation_deadline_is_declared_and_validated() -> None:
    observation_time = "2026-08-04T18:00:05+00:00"
    observation = _observation(observation_time)
    matrix = build_runtime_fault_matrix(
        matrix_id="council-reconciliation-deadline-config",
        source_revision=REVISION,
        observations=(observation,),
        generated_at=observation_time,
        catalog=RUNTIME_FAULT_CATALOG,
        provenance_origin="tests.council-reconciliation-deadline",
    )

    # The deadline is configurable: a one-second deadline makes the same
    # observation overdue two seconds later.
    tight = verify_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        trusted_observation_digests=(observation.digest,),
        now="2026-08-04T18:00:07+00:00",
        reconciliation_deadline_seconds=1,
    )
    assert f"fault.reconciliation-overdue:{SCENARIO_ID}" in tight.blockers

    # The conservative default is declared, positive, and matches the issuers'
    # default attestation validity of one day.
    assert RECONCILIATION_DEADLINE_SECONDS == 24 * 60 * 60

    for bad in (0, -1, float("nan"), float("inf"), True, "3600"):
        with pytest.raises(ValueError, match="reconciliation_deadline_seconds"):
            verify_runtime_fault_matrix(
                matrix,
                catalog=RUNTIME_FAULT_CATALOG,
                expected_source_revision=REVISION,
                trusted_observation_digests=(observation.digest,),
                now="2026-08-04T18:00:07+00:00",
                reconciliation_deadline_seconds=bad,  # type: ignore[arg-type]
            )

    with pytest.raises(ValueError, match="timezone-aware"):
        verify_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            trusted_observation_digests=(observation.digest,),
            now="2026-08-04T18:00:07",
        )
