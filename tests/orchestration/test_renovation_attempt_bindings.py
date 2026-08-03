from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from daedalus.orchestration import (
    RenovationAttemptBinding,
    RenovationAttemptBindingError,
    RenovationAttemptPlan,
    RenovationPlan,
    WorkItemContract,
    assemble_renovation_attempt_plan,
    load_renovation_attempt_plan,
    parse_renovation_attempt_plan,
    renovation_replay_key,
    verify_renovation_attempt_plan,
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
NOW = "2026-08-03T14:00:00+00:00"


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
            origin="tests.g1-attempt-snapshot",
            source_revision=revision,
            created_at=NOW,
            input_digests=(FOREST, *(plane.digest for plane in planes)),
            trace_id="g1.voltage-renovation",
        ),
    )


def _items(base: FourfoldSnapshot) -> tuple[WorkItemContract, WorkItemContract]:
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
            origin="tests.g1-attempt-work-item",
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
            origin="tests.g1-attempt-work-item",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(base.digest,),
            trace_id="g1.sync-event-representations",
        ),
    )
    return rename, sync


def _mission(
    base: FourfoldSnapshot, items: tuple[WorkItemContract, ...]
) -> MissionContract:
    return MissionContract(
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
            origin="tests.g1-attempt-mission",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(POLICY,),
            trace_id="g1.voltage-renovation",
        ),
    )


def _plan() -> tuple[
    RenovationPlan,
    MissionContract,
    FourfoldSnapshot,
    tuple[WorkItemContract, WorkItemContract],
]:
    base = _snapshot()
    items = _items(base)
    mission = _mission(base, items)
    value = RenovationPlan(
        plan_id="g1.voltage-renovation-plan",
        mission_id=mission.mission_id,
        mission_sha256=mission.digest,
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        work_items=items,
        provenance=ContractProvenance(
            origin="tests.g1-attempt-renovation-plan",
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
    return value, mission, base, items


def _attempt(item: WorkItemContract, mission: MissionContract) -> AttemptContract:
    return AttemptContract(
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
            origin="tests.g1-canonical-attempt",
            source_revision=item.base_revision,
            created_at=NOW,
            input_digests=(item.digest, RUNTIME, POLICY),
            trace_id=f"attempt.{item.work_item_id}",
        ),
        writable_paths=item.writable_paths,
        gate_names=item.required_evidence,
        read_only=False,
    )


def _assembled() -> tuple[
    RenovationAttemptPlan,
    RenovationPlan,
    MissionContract,
    FourfoldSnapshot,
]:
    plan, mission, base, items = _plan()
    attempts = tuple(_attempt(item, mission) for item in items)
    value = assemble_renovation_attempt_plan(
        renovation_plan=plan,
        mission=mission,
        base_snapshot=base,
        attempts=tuple(reversed(attempts)),
        expected_runtime_manifest_sha256=RUNTIME,
        expected_policy_decision_sha256=POLICY,
        attempt_plan_id="g1.voltage-attempt-plan",
        created_at=NOW,
    )
    return value, plan, mission, base


def _repack(
    value: RenovationAttemptPlan,
    bindings: tuple[RenovationAttemptBinding, ...],
) -> RenovationAttemptPlan:
    return dataclasses.replace(
        value,
        bindings=bindings,
        provenance=ContractProvenance(
            origin=value.provenance.origin,
            source_revision=value.base_revision,
            created_at=value.provenance.created_at,
            input_digests=(
                value.renovation_plan_sha256,
                *(binding.digest for binding in bindings),
            ),
            trace_id=value.provenance.trace_id,
        ),
    )


def test_exact_two_attempts_are_bound_in_dependency_order() -> None:
    value, plan, mission, base = _assembled()
    assert tuple(binding.sequence for binding in value.bindings) == (0, 1)
    assert tuple(binding.work_item_id for binding in value.bindings) == (
        "g1.rename-event-voltage",
        "g1.sync-event-representations",
    )
    assert len({binding.replay_key for binding in value.bindings}) == 2
    assert verify_renovation_attempt_plan(
        value,
        renovation_plan=plan,
        mission=mission,
        base_snapshot=base,
        expected_runtime_manifest_sha256=RUNTIME,
        expected_policy_decision_sha256=POLICY,
    ) is value
    assert RenovationAttemptPlan.from_dict(value.to_dict()) == value
    assert parse_renovation_attempt_plan(value.to_dict()) == value


def test_attempt_input_order_does_not_change_identity() -> None:
    plan, mission, base, items = _plan()
    attempts = tuple(_attempt(item, mission) for item in items)
    common = dict(
        renovation_plan=plan,
        mission=mission,
        base_snapshot=base,
        expected_runtime_manifest_sha256=RUNTIME,
        expected_policy_decision_sha256=POLICY,
        attempt_plan_id="g1.voltage-attempt-plan",
        created_at=NOW,
    )
    forward = assemble_renovation_attempt_plan(attempts=attempts, **common)
    reverse = assemble_renovation_attempt_plan(
        attempts=tuple(reversed(attempts)), **common
    )
    assert forward == reverse
    assert forward.digest == reverse.digest


def test_replay_key_binds_plan_item_attempt_and_sequence() -> None:
    value, _, _, _ = _assembled()
    first = value.bindings[0]
    assert first.replay_key == renovation_replay_key(
        renovation_plan_sha256=value.renovation_plan_sha256,
        work_item_sha256=first.work_item_sha256,
        attempt_sha256=first.attempt.digest,
        sequence=0,
    )
    assert first.replay_key != renovation_replay_key(
        renovation_plan_sha256=value.renovation_plan_sha256,
        work_item_sha256=first.work_item_sha256,
        attempt_sha256=first.attempt.digest,
        sequence=1,
    )


def test_caller_owned_runtime_and_policy_authority_are_required() -> None:
    value, plan, mission, base = _assembled()
    with pytest.raises(
        RenovationAttemptBindingError, match="runtime_manifest_sha256"
    ):
        verify_renovation_attempt_plan(
            value,
            renovation_plan=plan,
            mission=mission,
            base_snapshot=base,
            expected_runtime_manifest_sha256="a" * 64,
            expected_policy_decision_sha256=POLICY,
        )
    with pytest.raises(
        RenovationAttemptBindingError, match="policy_decision_sha256"
    ):
        verify_renovation_attempt_plan(
            value,
            renovation_plan=plan,
            mission=mission,
            base_snapshot=base,
            expected_runtime_manifest_sha256=RUNTIME,
            expected_policy_decision_sha256="b" * 64,
        )


def test_writable_paths_evidence_gates_and_budget_cannot_widen() -> None:
    value, plan, mission, base = _assembled()
    first = value.bindings[0]
    mutations = (
        dataclasses.replace(
            first.attempt,
            writable_paths=(*first.attempt.writable_paths, "src/foreign.py"),
        ),
        dataclasses.replace(
            first.attempt,
            gate_names=(first.attempt.gate_names[0],),
        ),
        dataclasses.replace(
            first.attempt,
            budget=ResourceBudget(max_wall_time_s=1801),
        ),
    )
    expected = ("writable_paths", "gate_names", "budget")
    for changed_attempt, marker in zip(mutations, expected):
        changed_replay = renovation_replay_key(
            renovation_plan_sha256=value.renovation_plan_sha256,
            work_item_sha256=first.work_item_sha256,
            attempt_sha256=changed_attempt.digest,
            sequence=first.sequence,
        )
        changed_binding = RenovationAttemptBinding(
            work_item_id=first.work_item_id,
            work_item_sha256=first.work_item_sha256,
            sequence=first.sequence,
            replay_key=changed_replay,
            attempt=changed_attempt,
            provenance=ContractProvenance(
                origin=first.provenance.origin,
                source_revision=first.provenance.source_revision,
                created_at=first.provenance.created_at,
                input_digests=(
                    first.work_item_sha256,
                    changed_attempt.digest,
                    changed_replay,
                ),
                trace_id=first.provenance.trace_id,
            ),
        )
        changed = _repack(value, (changed_binding, value.bindings[1]))
        with pytest.raises(RenovationAttemptBindingError, match=marker):
            verify_renovation_attempt_plan(
                changed,
                renovation_plan=plan,
                mission=mission,
                base_snapshot=base,
                expected_runtime_manifest_sha256=RUNTIME,
                expected_policy_decision_sha256=POLICY,
            )


def test_stale_plan_and_work_item_substitution_are_refused() -> None:
    value, plan, mission, base = _assembled()
    changed_plan = dataclasses.replace(
        plan,
        plan_id="g1.changed-renovation-plan",
    )
    with pytest.raises(RenovationAttemptBindingError, match="renovation_plan"):
        verify_renovation_attempt_plan(
            value,
            renovation_plan=changed_plan,
            mission=mission,
            base_snapshot=base,
            expected_runtime_manifest_sha256=RUNTIME,
            expected_policy_decision_sha256=POLICY,
        )
    stale_base = _snapshot(OTHER_REVISION)
    with pytest.raises(RenovationAttemptBindingError, match="not canonical"):
        verify_renovation_attempt_plan(
            value,
            renovation_plan=plan,
            mission=mission,
            base_snapshot=stale_base,
            expected_runtime_manifest_sha256=RUNTIME,
            expected_policy_decision_sha256=POLICY,
        )


def test_forged_sequence_and_replay_key_are_refused_after_valid_repackaging() -> None:
    value, plan, mission, base = _assembled()
    first, second = value.bindings
    forged_replay = "a" * 64
    forged_first = RenovationAttemptBinding(
        work_item_id=first.work_item_id,
        work_item_sha256=first.work_item_sha256,
        sequence=first.sequence,
        replay_key=forged_replay,
        attempt=first.attempt,
        provenance=ContractProvenance(
            origin=first.provenance.origin,
            source_revision=first.provenance.source_revision,
            created_at=first.provenance.created_at,
            input_digests=(
                first.work_item_sha256,
                first.attempt.digest,
                forged_replay,
            ),
            trace_id=first.provenance.trace_id,
        ),
    )
    forged = _repack(value, (forged_first, second))
    with pytest.raises(RenovationAttemptBindingError, match="replay_key"):
        verify_renovation_attempt_plan(
            forged,
            renovation_plan=plan,
            mission=mission,
            base_snapshot=base,
            expected_runtime_manifest_sha256=RUNTIME,
            expected_policy_decision_sha256=POLICY,
        )


def test_noncanonical_nested_wires_and_duplicate_keys_are_refused(
    tmp_path: Path,
) -> None:
    value, _, _, _ = _assembled()
    reordered = value.to_dict()
    reordered["bindings"] = list(reversed(reordered["bindings"]))
    with pytest.raises(RenovationAttemptBindingError, match="not canonical"):
        parse_renovation_attempt_plan(reordered)

    tuple_wire = value.to_dict()
    tuple_wire["bindings"][0]["attempt"]["gate_names"] = tuple(
        tuple_wire["bindings"][0]["attempt"]["gate_names"]
    )
    with pytest.raises(RenovationAttemptBindingError, match="not canonical"):
        parse_renovation_attempt_plan(tuple_wire)

    path = tmp_path / "attempt-plan.json"
    path.write_text(value.to_json(), encoding="utf-8")
    assert load_renovation_attempt_plan(path) == value
    duplicate = value.to_json().replace(
        '"attempt_plan_id":',
        '"attempt_plan_id":"duplicate","attempt_plan_id":',
        1,
    )
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(RenovationAttemptBindingError, match="duplicate JSON key"):
        load_renovation_attempt_plan(path)


def test_attempt_plan_has_no_lifecycle_or_promotion_state() -> None:
    value, _, _, _ = _assembled()
    wire = json.dumps(value.to_dict(), sort_keys=True)
    assert "execute" not in wire
    assert "started_at" not in wire
    assert "terminal" not in wire
    assert "owner_approval" not in wire
    assert "promotion" not in wire
