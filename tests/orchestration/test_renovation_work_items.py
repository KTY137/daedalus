from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from daedalus.orchestration import (
    RenovationPlan,
    RenovationPlanBindingError,
    RenovationPlanError,
    WorkItemContract,
    load_renovation_plan,
    parse_renovation_plan,
    verify_renovation_plan,
)
from daedalus.schemas import ContractProvenance, MissionContract, ResourceBudget
from daedalus.twin import FOURFOLD_PLANES, FourfoldSnapshot, PlaneSnapshot

REVISION = "1" * 40
OTHER_REVISION = "2" * 40
POLICY = "3" * 64
FOREST = "4" * 64
NOW = "2026-08-03T13:00:00+00:00"


def snapshot(revision: str = REVISION) -> FourfoldSnapshot:
    planes = tuple(
        PlaneSnapshot(
            plane=plane,
            source_revision=revision,
            status="complete",
            node_ids=(f"{plane}:node",),
            evidence_sha256s=(str(index + 5) * 64,),
        )
        for index, plane in enumerate(FOURFOLD_PLANES)
    )
    provenance = ContractProvenance(
        origin="tests.g1-renovation-snapshot",
        source_revision=revision,
        created_at=NOW,
        input_digests=(FOREST, *(plane.digest for plane in planes)),
        trace_id="g1-voltage-renovation",
    )
    return FourfoldSnapshot(
        repository_id="gate1-voltage-fixture",
        source_revision=revision,
        source_forest_sha256=FOREST,
        planes=planes,
        bindings=(),
        provenance=provenance,
    )


def work_items(base: FourfoldSnapshot) -> tuple[WorkItemContract, WorkItemContract]:
    rename = WorkItemContract(
        work_item_id="g1.rename-event-voltage",
        mission_id="g1.voltage-renovation",
        kind="symbol-rename",
        objective="Rename Event.voltage to Event.bias_voltage in Python and type contracts.",
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        plane_scope=("type", "code"),
        writable_paths=("src/event.py",),
        required_evidence=("python-tests", "type-contract"),
        depends_on=(),
        provenance=ContractProvenance(
            origin="tests.g1-work-item",
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
        objective="Synchronize bias_voltage across Markdown and CSV representations.",
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        plane_scope=("knowledge", "data"),
        writable_paths=("data/events.csv", "docs/events.md"),
        required_evidence=("csv-schema", "markdown-links", "round-trip"),
        depends_on=(rename.work_item_id,),
        provenance=ContractProvenance(
            origin="tests.g1-work-item",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(base.digest,),
            trace_id="g1.sync-event-representations",
        ),
    )
    return rename, sync


def mission(base: FourfoldSnapshot, items: tuple[WorkItemContract, ...]) -> MissionContract:
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
            origin="tests.g1-mission",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=(POLICY,),
            trace_id="g1.voltage-renovation",
        ),
    )


def plan(base: FourfoldSnapshot | None = None) -> tuple[RenovationPlan, MissionContract, FourfoldSnapshot]:
    base = base or snapshot()
    items = work_items(base)
    mission_value = mission(base, items)
    inputs = tuple(sorted({mission_value.digest, base.digest, *(item.digest for item in items)}))
    plan_value = RenovationPlan(
        plan_id="g1.voltage-renovation-plan",
        mission_id=mission_value.mission_id,
        mission_sha256=mission_value.digest,
        base_revision=base.source_revision,
        base_snapshot_sha256=base.digest,
        work_items=tuple(reversed(items)),
        provenance=ContractProvenance(
            origin="tests.g1-renovation-plan",
            source_revision=base.source_revision,
            created_at=NOW,
            input_digests=inputs,
            trace_id="g1.voltage-renovation-plan",
        ),
    )
    return plan_value, mission_value, base


def test_exact_two_item_voltage_plan_binds_all_four_planes() -> None:
    value, mission_value, base = plan()
    assert value.work_item_ids == tuple(sorted(mission_value.work_item_ids))
    assert {plane for item in value.work_items for plane in item.plane_scope} == set(
        FOURFOLD_PLANES
    )
    assert verify_renovation_plan(
        value, mission=mission_value, base_snapshot=base
    ) is value
    assert RenovationPlan.from_dict(value.to_dict()) == value
    assert parse_renovation_plan(value.to_dict()) == value


def test_plan_refuses_any_shape_other_than_two_typed_items() -> None:
    value, _, _ = plan()
    with pytest.raises(RenovationPlanError, match="exactly two"):
        dataclasses.replace(value, work_items=value.work_items[:1])
    with pytest.raises(RenovationPlanError, match="one symbol-rename"):
        dataclasses.replace(
            value,
            work_items=(
                value.work_items[0],
                dataclasses.replace(
                    value.work_items[0],
                    work_item_id="g1.rename-again",
                ),
            ),
        )


def test_dependency_and_plane_ownership_are_fail_closed() -> None:
    value, _, _ = plan()
    by_kind = {item.kind: item for item in value.work_items}
    with pytest.raises(RenovationPlanError, match="depend exactly"):
        dataclasses.replace(
            value,
            work_items=(
                by_kind["symbol-rename"],
                dataclasses.replace(by_kind["representation-sync"], depends_on=()),
            ),
        )
    with pytest.raises(RenovationPlanError, match="cover exactly"):
        dataclasses.replace(by_kind["symbol-rename"], plane_scope=("code", "data"))


def test_stale_mission_snapshot_and_item_identity_are_refused() -> None:
    value, mission_value, base = plan()
    stale = snapshot(OTHER_REVISION)
    with pytest.raises(RenovationPlanBindingError, match="base_snapshot_sha256"):
        verify_renovation_plan(value, mission=mission_value, base_snapshot=stale)
    changed_mission = dataclasses.replace(
        mission_value,
        objective=mission_value.objective + " Changed.",
    )
    with pytest.raises(RenovationPlanBindingError, match="mission_sha256"):
        verify_renovation_plan(value, mission=changed_mission, base_snapshot=base)
    changed_ids = dataclasses.replace(
        mission_value,
        work_item_ids=(mission_value.work_item_ids[0], "g1.foreign-work-item"),
    )
    with pytest.raises(RenovationPlanBindingError, match="work_item_ids"):
        verify_renovation_plan(value, mission=changed_ids, base_snapshot=base)


def test_noncanonical_and_duplicate_key_wires_are_refused() -> None:
    value, _, _ = plan()
    reordered = value.to_dict()
    reordered["work_items"] = list(reversed(reordered["work_items"]))
    with pytest.raises(RenovationPlanError, match="not canonical"):
        parse_renovation_plan(reordered)
    tuple_wire = value.to_dict()
    tuple_wire["work_items"] = tuple(tuple_wire["work_items"])
    with pytest.raises(RenovationPlanError, match="not canonical"):
        parse_renovation_plan(tuple_wire)


def test_overlapping_paths_and_provenance_substitution_are_refused() -> None:
    value, _, _ = plan()
    by_kind = {item.kind: item for item in value.work_items}
    overlapping_sync = dataclasses.replace(
        by_kind["representation-sync"],
        writable_paths=(by_kind["symbol-rename"].writable_paths[0],),
    )
    with pytest.raises(RenovationPlanError, match="disjoint"):
        dataclasses.replace(
            value,
            work_items=(by_kind["symbol-rename"], overlapping_sync),
        )
    weakened_inputs = value.provenance.input_digests[:-1]
    weakened = ContractProvenance(
        origin=value.provenance.origin,
        source_revision=value.provenance.source_revision,
        created_at=value.provenance.created_at,
        input_digests=weakened_inputs,
        trace_id=value.provenance.trace_id,
    )
    with pytest.raises(RenovationPlanError, match="bind exactly"):
        dataclasses.replace(value, provenance=weakened)


def test_forged_constructor_bypass_is_revalidated() -> None:
    value, mission_value, base = plan()
    forged = object.__new__(RenovationPlan)
    for field in dataclasses.fields(value):
        object.__setattr__(forged, field.name, getattr(value, field.name))
    object.__setattr__(forged, "work_items", value.work_items[:1])
    with pytest.raises(RenovationPlanBindingError, match="canonical contract"):
        verify_renovation_plan(forged, mission=mission_value, base_snapshot=base)


def test_loader_refuses_recursive_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_text(
        '{"contract_type":"daedalus.renovation-plan",'
        '"contract_type":"daedalus.renovation-plan"}',
        encoding="utf-8",
    )
    with pytest.raises(RenovationPlanError, match="duplicate JSON key"):
        load_renovation_plan(path)


def test_contract_module_has_no_execution_or_promotion_authority() -> None:
    path = Path(__file__).resolve().parents[2] / "daedalus" / "orchestration" / "work_items.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_imports = {"subprocess", "socket", "shutil", "tempfile"}
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported.intersection(forbidden_imports)
    source = path.read_text(encoding="utf-8")
    assert "OwnerApproval" not in source
    assert "EffectLease" not in source
    assert "promote_candidates" not in source
