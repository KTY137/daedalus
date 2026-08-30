# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The live-runtime collector: what it records, and what it refuses to record.

The collector is the seam that turns a probe's answer into a canonical
observation. Its job is to keep three states apart -- the invariant held, the
invariant broke, the harness could not tell -- and to make the third impossible
to mistake for the first.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import HostFaultFact
from daedalus.runtimes.live_fault_collector import (
    LiveFaultBindingMismatch,
    LiveFaultClockError,
    LiveProbeExecutorBinding,
    LiveProbeResult,
    load_live_fault_evidence_json,
    retain_live_fault_run,
    run_live_fault,
    run_live_fault_catalog,
)

REVISION = "d" * 40
NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)
EXPIRY = RUNTIME_FAULT_CATALOG.scenario_map["runtime.live-envelope.expiry"]
FIXTURE_ROW = RUNTIME_FAULT_CATALOG.scenario_map["runtime.broker.exact-replay-inert"]


def _clock():
    ticks = iter([NOW, NOW + timedelta(seconds=1)])
    return lambda: next(ticks)


def _binding(locator: str, result_or_error) -> LiveProbeExecutorBinding:
    def execute(scenario):
        if isinstance(result_or_error, Exception):
            raise result_or_error
        return result_or_error

    return LiveProbeExecutorBinding(
        locator=locator,
        implementation_sha256=hashlib.sha256(locator.encode()).hexdigest(),
        execute=execute,
    )


def _passing_result() -> LiveProbeResult:
    return LiveProbeResult(
        status="passed",
        observed_outcome="refused-before-start",
        detail_code=None,
        raw_evidence=b'{"observed":"refusal"}',
        facts=(HostFaultFact("control", "accepted-when-fresh"),),
    )


def test_a_passing_probe_becomes_a_bound_live_observation() -> None:
    run = run_live_fault(
        EXPIRY,
        source_revision=REVISION,
        executor=_binding(EXPIRY.executor, _passing_result()),
        clock=_clock(),
    )

    assert run.observation.authority == "live-runtime"
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "refused-before-start"
    assert run.observation.evidence_sha256 == run.evidence.digest
    assert run.evidence.raw_evidence_sha256 == hashlib.sha256(run.raw_evidence).hexdigest()


def test_a_missing_probe_is_blocked_and_never_silent() -> None:
    run = run_live_fault(
        EXPIRY, source_revision=REVISION, executor=None, clock=_clock()
    )

    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "live-probe-unavailable"


def test_a_raising_probe_fails_rather_than_disappearing() -> None:
    run = run_live_fault(
        EXPIRY,
        source_revision=REVISION,
        executor=_binding(EXPIRY.executor, RuntimeError("boom")),
        clock=_clock(),
    )

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "live-probe-error"


def test_a_probe_returning_a_foreign_type_fails() -> None:
    run = run_live_fault(
        EXPIRY,
        source_revision=REVISION,
        executor=_binding(EXPIRY.executor, "not a result"),
        clock=_clock(),
    )

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "live-probe-contract"


def test_a_probe_claiming_the_wrong_outcome_cannot_pass() -> None:
    """The collector compares the reported outcome against the catalog, not itself."""

    wrong = LiveProbeResult(
        status="passed",
        observed_outcome="cancelled",
        detail_code=None,
        raw_evidence=b'{"observed":"cancelled"}',
    )
    run = run_live_fault(
        EXPIRY,
        source_revision=REVISION,
        executor=_binding(EXPIRY.executor, wrong),
        clock=_clock(),
    )

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "outcome-mismatch"
    facts = {fact.name: fact.value for fact in run.evidence.facts}
    assert facts["collector-expected-outcome"] == "refused-before-start"
    assert facts["collector-reported-outcome"] == "cancelled"


def test_a_row_of_another_authority_is_refused() -> None:
    with pytest.raises(LiveFaultBindingMismatch, match="not a live-runtime scenario"):
        run_live_fault(
            FIXTURE_ROW,
            source_revision=REVISION,
            executor=None,
            clock=_clock(),
        )


def test_an_executor_bound_to_another_locator_is_refused() -> None:
    with pytest.raises(LiveFaultBindingMismatch, match="locator does not match"):
        run_live_fault(
            EXPIRY,
            source_revision=REVISION,
            executor=_binding("live-probe:runtime-binary-drift", _passing_result()),
            clock=_clock(),
        )


def test_a_locator_outside_this_column_cannot_be_bound() -> None:
    with pytest.raises(ValueError, match="must start with"):
        LiveProbeExecutorBinding(
            locator="pytest:tests/runtimes/test_x.py::test_y",
            implementation_sha256="0" * 64,
            execute=lambda scenario: _passing_result(),
        )


def test_a_backwards_clock_is_refused() -> None:
    ticks = iter([NOW, NOW - timedelta(seconds=5)])
    with pytest.raises(LiveFaultClockError, match="moved backwards"):
        run_live_fault(
            EXPIRY,
            source_revision=REVISION,
            executor=_binding(EXPIRY.executor, _passing_result()),
            clock=lambda: next(ticks),
        )


def test_the_catalog_run_covers_every_live_row_and_refuses_foreign_locators() -> None:
    runs = run_live_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=REVISION,
        executors={},
    )
    live_rows = [
        row for row in RUNTIME_FAULT_CATALOG.scenarios if row.authority == "live-runtime"
    ]

    assert len(runs) == len(live_rows) == 2
    assert all(row.observation.status == "blocked" for row in runs)

    with pytest.raises(LiveFaultBindingMismatch, match="foreign locators"):
        run_live_fault_catalog(
            catalog=RUNTIME_FAULT_CATALOG,
            source_revision=REVISION,
            executors={"live-probe:not-a-real-row": _binding(
                "live-probe:not-a-real-row", _passing_result()
            )},
        )


def test_evidence_survives_a_json_round_trip(tmp_path: Path) -> None:
    run = run_live_fault(
        EXPIRY,
        source_revision=REVISION,
        executor=_binding(EXPIRY.executor, _passing_result()),
        clock=_clock(),
    )
    restored = load_live_fault_evidence_json(json.dumps(run.evidence.to_dict()))

    assert restored.digest == run.evidence.digest


def test_retain_writes_the_triple_the_issuer_expects(tmp_path: Path) -> None:
    run = run_live_fault(
        EXPIRY,
        source_revision=REVISION,
        executor=_binding(EXPIRY.executor, _passing_result()),
        clock=_clock(),
    )
    retain_live_fault_run(tmp_path, run)

    scenario_id = run.observation.scenario_id
    assert (tmp_path / f"{scenario_id}.evidence.json").is_file()
    assert (tmp_path / f"{scenario_id}.observation.json").is_file()
    assert (tmp_path / f"{scenario_id}.raw").read_bytes() == run.raw_evidence
