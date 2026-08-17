"""The deterministic-fixture collector must never upgrade ignorance to a pass.

Every test here drives :func:`classify_pytest_invocation` with a synthetic
pytest result, so the collector's mapping is exercised without depending on the
repository's own suite being green. The central distinction under test is the
one the catalog cares about: a harness that could not determine the answer
(``blocked``) is not the same finding as an invariant that broke (``failed``),
and neither may become ``passed``.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.fixture_fault_collector import (
    FixtureFaultBindingMismatch,
    FixtureFaultClockError,
    FixtureFaultEvidence,
    FixtureFaultRun,
    PytestInvocation,
    classify_pytest_invocation,
    derive_terminal_outcome,
    parse_pytest_junit,
    report_runtime_fault_outcome,
    run_fixture_fault,
    run_fixture_fault_catalog,
    scenario_node_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "0" * 40


def _fixture_scenario(scenario_id: str = "runtime.fence.quarantine-wins"):
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[scenario_id]
    assert scenario.authority == "deterministic-fixture"
    return scenario


def _junit(
    *,
    name: str = "test_example",
    verdict: str = "passed",
    properties: dict[str, str] | None = None,
    cases: int = 1,
) -> str:
    body = []
    for index in range(cases):
        inner = ""
        if properties:
            rendered = "".join(
                f'<property name="{key}" value="{value}" />'
                for key, value in properties.items()
            )
            inner += f"<properties>{rendered}</properties>"
        if verdict == "failed":
            inner += '<failure message="assert 1 == 2">boom</failure>'
        elif verdict == "error":
            inner += '<error message="IndentationError">unexpected indent</error>'
        elif verdict == "skipped":
            inner += '<skipped message="needs docker" />'
        body.append(
            f'<testcase classname="t" name="{name}{index if cases > 1 else ""}" '
            f'time="0.1">{inner}</testcase>'
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        f'tests="{cases}">{"".join(body)}</testsuite></testsuites>'
    )


def _outcome_xml(outcome: str) -> str:
    return _junit(properties={"runtime_fault_observed_outcome": outcome})


def _classify(scenario, invocation: PytestInvocation):
    return classify_pytest_invocation(scenario, scenario_node_id(scenario), invocation)


def test_clean_run_reporting_the_expected_outcome_passes() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(
            exit_code=0, stdout="1 passed", junit_xml=_outcome_xml(scenario.expected_outcome)
        ),
    )
    assert result.status == "passed"
    assert result.observed_outcome == scenario.expected_outcome
    assert result.detail_code is None


def test_green_node_that_reports_no_outcome_is_blocked_not_passed() -> None:
    """A zero exit code is not evidence that the required state was reached."""

    scenario = _fixture_scenario()
    result = _classify(
        scenario, PytestInvocation(exit_code=0, stdout="1 passed", junit_xml=_junit())
    )
    assert result.status == "blocked"
    assert result.detail_code == "outcome-unreported"
    assert result.observed_outcome is None


def test_reported_outcome_that_contradicts_the_catalog_fails() -> None:
    scenario = _fixture_scenario()
    other = "unknown-reconciled"
    assert other != scenario.expected_outcome
    result = _classify(
        scenario, PytestInvocation(exit_code=0, stdout="1 passed", junit_xml=_outcome_xml(other))
    )
    assert result.status == "failed"
    assert result.detail_code == "outcome-mismatch"
    assert result.observed_outcome == other


def test_uninterpretable_reported_outcome_is_blocked() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(exit_code=0, stdout="1 passed", junit_xml=_outcome_xml("green")),
    )
    assert result.status == "blocked"
    assert result.detail_code == "outcome-uninterpretable"


def test_failing_assertions_are_failed_without_an_invented_outcome() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(exit_code=1, stdout="1 failed", junit_xml=_junit(verdict="failed")),
    )
    assert result.status == "failed"
    assert result.detail_code == "assertion-failed"
    assert result.observed_outcome is None


def test_collection_error_is_blocked_because_it_is_not_a_red_test() -> None:
    """An IndentationError never exercised the invariant, so it is not a failure."""

    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(exit_code=2, stdout="ERROR", junit_xml=_junit(verdict="error")),
    )
    assert result.status == "blocked"
    assert result.detail_code == "collection-error"


def test_missing_node_is_blocked_as_a_stale_locator() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario, PytestInvocation(exit_code=5, stdout="no tests ran", junit_xml="")
    )
    assert result.status == "blocked"
    assert result.detail_code == "node-missing"


def test_timeout_is_blocked_with_its_own_reason() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(exit_code=-1, stdout="timeout", junit_xml="", timed_out=True),
    )
    assert result.status == "blocked"
    assert result.detail_code == "execution-timeout"


def test_skipped_node_is_blocked() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(exit_code=0, stdout="1 skipped", junit_xml=_junit(verdict="skipped")),
    )
    assert result.status == "blocked"
    assert result.detail_code == "test-skipped"


def test_ambiguous_node_matching_several_testcases_is_blocked() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(exit_code=0, stdout="2 passed", junit_xml=_junit(cases=2)),
    )
    assert result.status == "blocked"
    assert result.detail_code == "node-ambiguous"


def test_green_testcase_inside_a_dirty_session_is_blocked() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario,
        PytestInvocation(
            exit_code=3,
            stdout="INTERNALERROR",
            junit_xml=_outcome_xml(scenario.expected_outcome),
        ),
    )
    assert result.status == "blocked"
    assert result.detail_code == "session-not-clean"


def test_unreadable_junit_is_blocked() -> None:
    scenario = _fixture_scenario()
    result = _classify(
        scenario, PytestInvocation(exit_code=0, stdout="", junit_xml="<not-xml")
    )
    assert result.status == "blocked"
    assert result.detail_code == "junit-unreadable"


def test_runner_that_raises_is_blocked_and_never_fails_the_invariant() -> None:
    scenario = _fixture_scenario()

    def broken(_node_id: str) -> PytestInvocation:
        raise OSError("no interpreter")

    run = run_fixture_fault(
        scenario,
        source_revision=REVISION,
        runner=broken,
        repo_root=REPO_ROOT,
    )
    assert run.observation.status == "blocked"
    assert run.observation.detail_code == "runner-error"


def test_run_binds_raw_evidence_evidence_and_observation() -> None:
    scenario = _fixture_scenario()
    run = run_fixture_fault(
        scenario,
        source_revision=REVISION,
        runner=lambda _node: PytestInvocation(
            exit_code=0, stdout="1 passed", junit_xml=_outcome_xml(scenario.expected_outcome)
        ),
        repo_root=REPO_ROOT,
    )
    assert run.observation.authority == "deterministic-fixture"
    assert run.observation.status == "passed"
    assert run.observation.evidence_sha256 == run.evidence.digest
    assert (
        hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256
    )
    assert run.observation.scenario_sha256 == scenario.digest
    assert run.evidence.schema == "daedalus-fixture-fault-evidence/1"
    # The evidence names the exact test source that produced it.
    node_path = REPO_ROOT / scenario_node_id(scenario).split("::", 1)[0]
    assert run.evidence.executor_sha256 == hashlib.sha256(node_path.read_bytes()).hexdigest()


def test_swapping_evidence_between_two_runs_is_refused() -> None:
    first = _fixture_scenario("runtime.fence.quarantine-wins")
    second = _fixture_scenario("runtime.fence.shared-ledger")
    runner = lambda node: PytestInvocation(  # noqa: E731
        exit_code=0, stdout="", junit_xml=_junit()
    )
    run_a = run_fixture_fault(
        first, source_revision=REVISION, runner=runner, repo_root=REPO_ROOT
    )
    run_b = run_fixture_fault(
        second, source_revision=REVISION, runner=runner, repo_root=REPO_ROOT
    )
    with pytest.raises(FixtureFaultBindingMismatch):
        FixtureFaultRun(
            evidence=run_a.evidence,
            observation=run_b.observation,
            raw_evidence=run_a.raw_evidence,
        )


def test_backwards_clock_is_refused() -> None:
    scenario = _fixture_scenario()
    stamps = iter(
        [
            datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc),
        ]
    )
    with pytest.raises(FixtureFaultClockError):
        run_fixture_fault(
            scenario,
            source_revision=REVISION,
            runner=lambda _node: PytestInvocation(exit_code=0, stdout="", junit_xml=_junit()),
            repo_root=REPO_ROOT,
            clock=lambda: next(stamps),
        )


def test_naive_clock_is_refused() -> None:
    scenario = _fixture_scenario()
    with pytest.raises(FixtureFaultClockError):
        run_fixture_fault(
            scenario,
            source_revision=REVISION,
            runner=lambda _node: PytestInvocation(exit_code=0, stdout="", junit_xml=_junit()),
            repo_root=REPO_ROOT,
            clock=lambda: datetime(2026, 8, 17, 12, 0),
        )


def test_non_fixture_scenario_is_refused_by_node_resolution() -> None:
    host = RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.timeout"]
    assert host.authority == "linux-host"
    with pytest.raises(FixtureFaultBindingMismatch):
        scenario_node_id(host)


def test_catalog_run_covers_every_fixture_row_exactly_once() -> None:
    expected = tuple(
        row.scenario_id
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.authority == "deterministic-fixture"
    )
    runs = run_fixture_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=REVISION,
        runner=lambda _node: PytestInvocation(exit_code=5, stdout="", junit_xml=""),
        repo_root=REPO_ROOT,
    )
    assert tuple(run.observation.scenario_id for run in runs) == expected
    assert len(expected) == 13
    assert {run.observation.status for run in runs} == {"blocked"}


def test_passed_evidence_cannot_be_constructed_without_an_outcome() -> None:
    scenario = _fixture_scenario()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with pytest.raises(ValueError):
        FixtureFaultEvidence(
            schema="daedalus-fixture-fault-evidence/1",
            scenario_id=scenario.scenario_id,
            scenario_sha256=scenario.digest,
            source_revision=REVISION,
            executor=scenario.executor,
            executor_sha256="a" * 64,
            started_at=now,
            finished_at=now,
            status="passed",
            observed_outcome=None,
            detail_code=None,
            raw_evidence_sha256="b" * 64,
            facts=(),
        )


def test_blocked_evidence_cannot_invent_an_outcome() -> None:
    scenario = _fixture_scenario()
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with pytest.raises(ValueError):
        FixtureFaultEvidence(
            schema="daedalus-fixture-fault-evidence/1",
            scenario_id=scenario.scenario_id,
            scenario_sha256=scenario.digest,
            source_revision=REVISION,
            executor=scenario.executor,
            executor_sha256="a" * 64,
            started_at=now,
            finished_at=(
                datetime.now(timezone.utc) + timedelta(seconds=1)
            ).isoformat(timespec="microseconds"),
            status="blocked",
            observed_outcome="cancelled",
            detail_code="node-missing",
            raw_evidence_sha256="b" * 64,
            facts=(),
        )


def test_derived_outcomes_cover_the_terminal_vocabulary() -> None:
    assert derive_terminal_outcome(terminal_outcome=None) == "refused-before-start"
    assert (
        derive_terminal_outcome(terminal_outcome="cancelled", execution_state="CANCELLED")
        == "cancelled"
    )
    assert (
        derive_terminal_outcome(terminal_outcome="COMPLETED", execution_state="completed")
        == "completed-before-quarantine"
    )
    assert derive_terminal_outcome(terminal_outcome="failed") == "failed"


def test_derivation_refuses_contradictions_and_unknown_terminals() -> None:
    """The node cannot report an outcome its own observations do not support."""

    with pytest.raises(ValueError):
        derive_terminal_outcome(terminal_outcome=None, execution_state="COMPLETED")
    with pytest.raises(ValueError):
        derive_terminal_outcome(terminal_outcome="completed", execution_state="CANCELLED")
    with pytest.raises(ValueError):
        derive_terminal_outcome(terminal_outcome="in-flight")


def test_pending_reconciliation_is_named_only_for_a_durable_started_effect() -> None:
    assert (
        derive_terminal_outcome(
            terminal_outcome=None,
            execution_state="STARTED",
            reconciliation_pending=True,
        )
        == "started-unreconciled"
    )
    # Without the explicit flag the same pair is still refused, so a node cannot
    # slide into the token by forgetting an argument.
    with pytest.raises(ValueError):
        derive_terminal_outcome(terminal_outcome=None, execution_state="STARTED")
    # And the flag cannot launder a state that did reach a terminal, or one that
    # never became durable at all.
    for state in ("COMPLETED", "CANCELLED", "FAILED", None):
        with pytest.raises(ValueError):
            derive_terminal_outcome(
                terminal_outcome=None,
                execution_state=state,
                reconciliation_pending=True,
            )
    with pytest.raises(ValueError):
        derive_terminal_outcome(
            terminal_outcome="failed",
            execution_state="STARTED",
            reconciliation_pending=True,
        )


def test_reporting_helper_records_the_property_the_collector_reads() -> None:
    recorded: list[tuple[str, str]] = []
    outcome = report_runtime_fault_outcome(
        lambda name, value: recorded.append((name, value)),
        terminal_outcome="cancelled",
        execution_state="CANCELLED",
    )
    assert outcome == "cancelled"
    assert recorded == [("runtime_fault_observed_outcome", "cancelled")]


# Executor locators that do not resolve at this revision. Every entry would be a
# catalog row whose pytest node id names a test that does not exist, so the row
# could only ever be blocked as node-missing. The set is empty at this revision
# and stays pinned rather than merely observed: renaming or deleting a named node
# must turn this test red and force the inventory to be updated in the same beat,
# instead of quietly degrading a matrix row into a block.
UNRESOLVED_FIXTURE_LOCATORS: frozenset[str] = frozenset()


def _collected_node_ids(relative_paths: set[str]) -> set[str]:
    import subprocess
    import sys

    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *sorted(relative_paths), "--collect-only", "-q"],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if "::" in line
    }


def test_fixture_locator_resolution_matches_the_pinned_inventory() -> None:
    scenarios = [
        row
        for row in RUNTIME_FAULT_CATALOG.scenarios
        if row.authority == "deterministic-fixture"
    ]
    node_ids = {row.scenario_id: scenario_node_id(row) for row in scenarios}
    collected = _collected_node_ids(
        {node.split("::", 1)[0] for node in node_ids.values()}
    )
    unresolved = {
        scenario_id
        for scenario_id, node in node_ids.items()
        if node.replace("\\", "/") not in collected
    }
    assert unresolved == UNRESOLVED_FIXTURE_LOCATORS


def test_junit_parsing_reports_verdicts_and_properties() -> None:
    reports = parse_pytest_junit(_outcome_xml("cancelled"))
    assert len(reports) == 1
    assert reports[0].verdict == "passed"
    assert reports[0].reported_outcome == "cancelled"
    assert parse_pytest_junit("") == ()
