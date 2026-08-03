from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from daedalus.orchestration import (
    AttemptLifecycleObservation,
    RenovationAttemptPlan,
    RenovationReplayDecision,
    RenovationReplayError,
    RenovationReplayPlan,
    RenovationPlan,
    WorkItemContract,
    assemble_renovation_attempt_plan,
    assemble_renovation_replay_plan,
    load_renovation_replay_plan,
    parse_attempt_lifecycle_observation,
    parse_renovation_replay_plan,
    verify_renovation_replay_plan,
)
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    MissionContract,
    ResourceBudget,
)
from daedalus.twin import FOURFOLD_PLANES, FourfoldSnapshot, PlaneSnapshot

REVISION = "1" * 40
OTHER_REVISION = "2" * 40
POLICY = "3" * 64
RUNTIME = "4" * 64
FOREST = "5" * 64
NOW = "2026-08-03T15:00:00+00:00"


def _snapshot(revision: str = REVISION) -> FourfoldSnapshot:
    planes = tuple(
        PlaneSnapshot(
            plane=plane,
            source_revision=revision,
            status="complete",
            node_ids=(f"{plane}:event-voltage",),
            evidence_sha256s=(str(index + 6) * 64,),
        )
        for index, plane in enumerate(FOURFOLD_PLANES)
    )
    return FourfoldSnapshot(
        repository_id="gate1-voltage-fixture",
        source_revision=revision,
        source_forest_sha256=FOREST,
        planes=planes,
        bindings=(),
        provenance=ContractProvenance(
            origin="tests.g1-replay-snapshot",
            source_revision=revision,
            created_at=NOW,
            input_digests=(FOREST, *(plane.digest for plane in planes)),
            trace_id="g1.voltage-renovation",
        ),
    )


def _work_items(
    base: FourfoldSnapshot,
) -> tuple[WorkItemContract, WorkItemContract]:
    rename = WorkItemContract(
        work_item_id="g1.rename-event-voltage",
        mission_id="g1.voltage-renovation",
        kind="symbol-rename",
        objective="Rename Event.voltage to Event.bias_voltage in Python and types.",
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        plane_scope=("code", "type"),
        writable_paths=("src/event.py",),
        required_evidence=("python-tests", "type-contract"),
        depends_on=(),
        provenance=ContractProvenance(
            origin="tests.g1-replay-work-item",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(base.digest,),
            trace_id="g1.rename-event-voltage",
        ),
    )
    sync = WorkItemContract(
        work_item_id="g1.sync-event-representations",
        mission_id="g1.voltage-renovation",
        kind="representation-sync",
        objective="Synchronize bias_voltage across Markdown and CSV.",
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        plane_scope=("data", "knowledge"),
        writable_paths=("data/events.csv", "docs/events.md"),
        required_evidence=("csv-schema", "markdown-links", "round-trip"),
        depends_on=(rename.work_item_id,),
        provenance=ContractProvenance(
            origin="tests.g1-replay-work-item",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(base.digest,),
            trace_id="g1.sync-event-representations",
        ),
    )
    return rename, sync


def _authority() -> tuple[
    RenovationAttemptPlan,
    RenovationPlan,
    MissionContract,
    FourfoldSnapshot,
]:
    base = _snapshot()
    items = _work_items(base)
    mission = MissionContract(
        mission_id="g1.voltage-renovation",
        objective="Propagate Event.voltage to bias_voltage across Python, Markdown, and CSV.",
        source_revision=base.source_revision,
        work_item_ids=tuple(item.work_item_id for item in items),
        success_criteria=(
            "behavior-tests-pass",
            "csv-schema-valid",
            "markdown-links-valid",
            "round-trip-matches-target",
        ),
        policy_sha256=POLICY,
        budget=ResourceBudget(
            max_tokens=100000,
            max_cost_microusd=500000,
            max_wall_time_s=1800,
            max_attempts=4,
        ),
        provenance=ContractProvenance(
            origin="tests.g1-replay-mission",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(POLICY,),
            trace_id="g1.voltage-renovation",
        ),
    )
    plan = RenovationPlan(
        plan_id="g1.voltage-renovation-plan",
        mission_id=mission.mission_id,
        mission_sha256=mission.digest,
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        work_items=items,
        provenance=ContractProvenance(
            origin="tests.g1-replay-renovation-plan",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(
                mission.digest,
                base.digest,
                *(item.digest for item in items),
            ),
            trace_id="g1.voltage-renovation-plan",
        ),
    )
    attempts = tuple(
        AttemptContract(
            attempt_id=f"attempt.{item.work_item_id}",
            mission_id=mission.mission_id,
            task_id=item.work_item_id,
            instruction=item.objective,
            base_revision=item.base_revision,
            task_sha256=item.digest,
            runtime_manifest_sha256=RUNTIME,
            policy_decision_sha256=POLICY,
            budget=mission.budget,
            provenance=ContractProvenance(
                origin="tests.g1-replay-attempt",
                source_revision=item.base_revision,
                created_at=NOW,
                input_digests=(item.digest, RUNTIME, POLICY),
                trace_id=f"attempt.{item.work_item_id}",
            ),
            writable_paths=item.writable_paths,
            gate_names=item.required_evidence,
            read_only=False,
        )
        for item in items
    )
    attempt_plan = assemble_renovation_attempt_plan(
        renovation_plan=plan,
        mission=mission,
        base_snapshot=base,
        attempts=attempts,
        expected_runtime_manifest_sha256=RUNTIME,
        expected_policy_decision_sha256=POLICY,
        attempt_plan_id="g1.voltage-attempt-plan",
        created_at=NOW,
    )
    return attempt_plan, plan, mission, base


def _receipt(sequence: int, terminal: bool = False) -> str:
    value = 10 + sequence * 2 + int(terminal)
    return f"{value:x}" * 64


def _observation(
    binding,
    state: str,
    *,
    revision: str = REVISION,
) -> AttemptLifecycleObservation:
    start = None if state == "not-started" else _receipt(binding.sequence)
    terminal = _receipt(binding.sequence, terminal=True) if state in {
        "succeeded",
        "failed",
        "cancelled",
    } else None
    inputs = tuple(
        digest
        for digest in (binding.attempt.digest, binding.replay_key, start, terminal)
        if digest is not None
    )
    return AttemptLifecycleObservation(
        attempt_id=binding.attempt.attempt_id,
        attempt_sha256=binding.attempt.digest,
        replay_key=binding.replay_key,
        sequence=binding.sequence,
        state=state,
        start_receipt_sha256=start,
        terminal_receipt_sha256=terminal,
        source_revision=revision,
        provenance=ContractProvenance(
            origin="tests.g1-replay-observation",
            source_revision=revision,
            created_at=NOW,
            input_digests=inputs,
            trace_id=binding.attempt.attempt_id,
        ),
    )


def _assemble(states: tuple[str, str]) -> tuple[
    RenovationReplayPlan,
    RenovationAttemptPlan,
    RenovationPlan,
    MissionContract,
    FourfoldSnapshot,
    tuple[AttemptLifecycleObservation, AttemptLifecycleObservation],
]:
    attempt_plan, plan, mission, base = _authority()
    observations = tuple(
        _observation(binding, state)
        for binding, state in zip(attempt_plan.bindings, states)
    )
    replay = assemble_renovation_replay_plan(
        attempt_plan=attempt_plan,
        renovation_plan=plan,
        mission=mission,
        base_snapshot=base,
        observations=tuple(reversed(observations)),
        expected_runtime_manifest_sha256=RUNTIME,
        expected_policy_decision_sha256=POLICY,
        replay_plan_id="g1.voltage-replay-plan",
        created_at=NOW,
    )
    return replay, attempt_plan, plan, mission, base, observations


def _verify(
    replay: RenovationReplayPlan,
    attempt_plan: RenovationAttemptPlan,
    plan: RenovationPlan,
    mission: MissionContract,
    base: FourfoldSnapshot,
    observations,
) -> RenovationReplayPlan:
    return verify_renovation_replay_plan(
        replay,
        attempt_plan=attempt_plan,
        renovation_plan=plan,
        mission=mission,
        base_snapshot=base,
        observations=observations,
        expected_runtime_manifest_sha256=RUNTIME,
        expected_policy_decision_sha256=POLICY,
    )


def test_fresh_plan_executes_first_and_blocks_dependent_attempt() -> None:
    replay, attempt_plan, plan, mission, base, observations = _assemble(
        ("not-started", "not-started")
    )
    assert tuple(decision.action for decision in replay.decisions) == (
        "execute",
        "blocked-dependency",
    )
    assert _verify(replay, attempt_plan, plan, mission, base, observations) is replay
    assert RenovationReplayPlan.from_dict(replay.to_dict()) == replay
    assert parse_renovation_replay_plan(replay.to_dict()) == replay


def test_successful_first_attempt_replays_terminal_and_releases_second() -> None:
    replay, *_ = _assemble(("succeeded", "not-started"))
    assert tuple(decision.action for decision in replay.decisions) == (
        "return-terminal",
        "execute",
    )
    assert replay.decisions[0].terminal_receipt_sha256 == _receipt(0, terminal=True)


@pytest.mark.parametrize("state", ["started", "unknown"])
def test_in_flight_or_unknown_outcome_requires_reconciliation(state: str) -> None:
    replay, *_ = _assemble((state, "not-started"))
    assert tuple(decision.action for decision in replay.decisions) == (
        "reconcile",
        "blocked-dependency",
    )


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_terminal_failure_requires_new_attempt_not_duplicate_execution(state: str) -> None:
    replay, *_ = _assemble((state, "not-started"))
    assert tuple(decision.action for decision in replay.decisions) == (
        "restart-required",
        "blocked-dependency",
    )


def test_dependent_attempt_cannot_have_lifecycle_before_first_success() -> None:
    attempt_plan, plan, mission, base = _authority()
    observations = (
        _observation(attempt_plan.bindings[0], "failed"),
        _observation(attempt_plan.bindings[1], "started"),
    )
    with pytest.raises(RenovationReplayError, match="before sequence 0 succeeds"):
        assemble_renovation_replay_plan(
            attempt_plan=attempt_plan,
            renovation_plan=plan,
            mission=mission,
            base_snapshot=base,
            observations=observations,
            expected_runtime_manifest_sha256=RUNTIME,
            expected_policy_decision_sha256=POLICY,
            replay_plan_id="g1.voltage-replay-plan",
            created_at=NOW,
        )


def test_observation_state_and_receipt_shapes_fail_closed() -> None:
    attempt_plan, _, _, _ = _authority()
    binding = attempt_plan.bindings[0]
    common = dict(
        attempt_id=binding.attempt.attempt_id,
        attempt_sha256=binding.attempt.digest,
        replay_key=binding.replay_key,
        sequence=0,
        source_revision=REVISION,
    )
    with pytest.raises(RenovationReplayError, match="must not retain"):
        AttemptLifecycleObservation(
            state="not-started",
            start_receipt_sha256=_receipt(0),
            terminal_receipt_sha256=None,
            provenance=ContractProvenance(
                origin="tests.g1-replay-observation",
                source_revision=REVISION,
                created_at=NOW,
                input_digests=(
                    binding.attempt.digest,
                    binding.replay_key,
                    _receipt(0),
                ),
            ),
            **common,
        )
    with pytest.raises(RenovationReplayError, match="requires start and terminal"):
        AttemptLifecycleObservation(
            state="succeeded",
            start_receipt_sha256=_receipt(0),
            terminal_receipt_sha256=None,
            provenance=ContractProvenance(
                origin="tests.g1-replay-observation",
                source_revision=REVISION,
                created_at=NOW,
                input_digests=(
                    binding.attempt.digest,
                    binding.replay_key,
                    _receipt(0),
                ),
            ),
            **common,
        )


def test_foreign_attempt_replay_key_and_stale_revision_are_refused() -> None:
    attempt_plan, plan, mission, base = _authority()
    first, second = attempt_plan.bindings
    valid_second = _observation(second, "not-started")
    mutations = (
        dataclasses.replace(
            _observation(first, "not-started"),
            attempt_sha256="a" * 64,
            provenance=ContractProvenance(
                origin="tests.g1-replay-observation",
                source_revision=REVISION,
                created_at=NOW,
                input_digests=("a" * 64, first.replay_key),
                trace_id=first.attempt.attempt_id,
            ),
        ),
        dataclasses.replace(
            _observation(first, "not-started"),
            replay_key="b" * 64,
            provenance=ContractProvenance(
                origin="tests.g1-replay-observation",
                source_revision=REVISION,
                created_at=NOW,
                input_digests=(first.attempt.digest, "b" * 64),
                trace_id=first.attempt.attempt_id,
            ),
        ),
        _observation(first, "not-started", revision=OTHER_REVISION),
    )
    expected = ("attempt_sha256", "replay_key", "source_revision")
    for changed, marker in zip(mutations, expected):
        with pytest.raises(RenovationReplayError, match=marker):
            assemble_renovation_replay_plan(
                attempt_plan=attempt_plan,
                renovation_plan=plan,
                mission=mission,
                base_snapshot=base,
                observations=(changed, valid_second),
                expected_runtime_manifest_sha256=RUNTIME,
                expected_policy_decision_sha256=POLICY,
                replay_plan_id="g1.voltage-replay-plan",
                created_at=NOW,
            )


def test_current_authority_recomputes_and_rejects_forged_action() -> None:
    replay, attempt_plan, plan, mission, base, observations = _assemble(
        ("not-started", "not-started")
    )
    first = replay.decisions[0]
    forged_first = dataclasses.replace(first, action="blocked-dependency")
    forged = dataclasses.replace(
        replay,
        decisions=(forged_first, replay.decisions[1]),
        provenance=ContractProvenance(
            origin=replay.provenance.origin,
            source_revision=replay.base_revision,
            created_at=replay.provenance.created_at,
            input_digests=(
                replay.attempt_plan_sha256,
                forged_first.digest,
                replay.decisions[1].digest,
            ),
            trace_id=replay.provenance.trace_id,
        ),
    )
    with pytest.raises(RenovationReplayError, match="recomputed"):
        _verify(forged, attempt_plan, plan, mission, base, observations)


def test_noncanonical_wires_and_duplicate_keys_are_refused(tmp_path: Path) -> None:
    replay, *_ = _assemble(("succeeded", "not-started"))
    observation = _observation(_authority()[0].bindings[0], "not-started")
    assert parse_attempt_lifecycle_observation(observation.to_dict()) == observation

    reordered = replay.to_dict()
    reordered["decisions"] = list(reversed(reordered["decisions"]))
    with pytest.raises(RenovationReplayError, match="not canonical"):
        parse_renovation_replay_plan(reordered)

    tuple_wire = replay.to_dict()
    tuple_wire["decisions"][0]["provenance"]["input_digests"] = tuple(
        tuple_wire["decisions"][0]["provenance"]["input_digests"]
    )
    with pytest.raises(RenovationReplayError, match="not canonical"):
        parse_renovation_replay_plan(tuple_wire)

    path = tmp_path / "replay-plan.json"
    path.write_text(replay.to_json(), encoding="utf-8")
    assert load_renovation_replay_plan(path) == replay
    duplicate = replay.to_json().replace(
        '"replay_plan_id":',
        '"replay_plan_id":"duplicate","replay_plan_id":',
        1,
    )
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(RenovationReplayError, match="duplicate JSON key"):
        load_renovation_replay_plan(path)


def test_decision_constructor_cannot_relabel_started_as_execute() -> None:
    attempt_plan, _, _, _ = _authority()
    observation = _observation(attempt_plan.bindings[0], "started")
    with pytest.raises(RenovationReplayError, match="invalid for state"):
        RenovationReplayDecision(
            work_item_id=attempt_plan.bindings[0].work_item_id,
            attempt_id=observation.attempt_id,
            attempt_sha256=observation.attempt_sha256,
            replay_key=observation.replay_key,
            sequence=0,
            observed_state="started",
            action="execute",
            start_receipt_sha256=observation.start_receipt_sha256,
            terminal_receipt_sha256=None,
            source_revision=REVISION,
            provenance=ContractProvenance(
                origin="tests.g1-replay-decision",
                source_revision=REVISION,
                created_at=NOW,
                input_digests=(
                    observation.attempt_sha256,
                    observation.replay_key,
                    observation.start_receipt_sha256,
                ),
            ),
        )
