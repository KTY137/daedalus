"""Typed, non-executing work-plan contracts for Renovation missions.

The contracts in this module describe work. They do not create attempts, grant
an effect, mutate a checkout, publish evidence, nominate a candidate, or
promote one. Execution remains behind the canonical kernel and effect boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    MissionContract,
    _identifier,
    _non_empty,
    _revision,
    _sha256,
    _sorted_strings,
)
from daedalus.twin import FOURFOLD_PLANES, FourfoldSnapshot

_WORK_KINDS = {
    "symbol-rename": frozenset({"code", "type"}),
    "representation-sync": frozenset({"data", "knowledge"}),
}


class RenovationPlanError(ValueError):
    """Base error for malformed or contradictory Renovation planning data."""


class RenovationPlanBindingError(RenovationPlanError):
    """A plan does not bind the expected mission or Fourfold snapshot."""


@dataclass(frozen=True)
class WorkItemContract(CanonicalContract):
    """One typed, bounded unit of work inside a Renovation mission."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.work-item"

    work_item_id: str
    mission_id: str
    kind: str
    objective: str
    base_revision: str
    base_snapshot_sha256: str
    plane_scope: tuple[str, ...]
    writable_paths: tuple[str, ...]
    required_evidence: tuple[str, ...]
    depends_on: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("work_item_id", "mission_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.kind not in _WORK_KINDS:
            raise RenovationPlanError(
                "work item kind must be symbol-rename or representation-sync"
            )
        object.__setattr__(
            self, "objective", _non_empty(self.objective, "objective", max_length=8000)
        )
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "base_snapshot_sha256",
            _sha256(self.base_snapshot_sha256, "base_snapshot_sha256"),
        )
        object.__setattr__(
            self,
            "plane_scope",
            _sorted_strings(self.plane_scope, "plane_scope", identifiers=True),
        )
        expected_planes = _WORK_KINDS[self.kind]
        if set(self.plane_scope) != expected_planes:
            raise RenovationPlanError(
                f"{self.kind} must cover exactly {sorted(expected_planes)}"
            )
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        if not self.writable_paths:
            raise RenovationPlanError("work item must declare bounded writable paths")
        if any(path == "." for path in self.writable_paths):
            raise RenovationPlanError("work item must not claim the repository root")
        object.__setattr__(
            self,
            "required_evidence",
            _sorted_strings(
                self.required_evidence, "required_evidence", identifiers=True
            ),
        )
        if not self.required_evidence:
            raise RenovationPlanError("work item must require deterministic evidence")
        object.__setattr__(
            self,
            "depends_on",
            _sorted_strings(self.depends_on, "depends_on", identifiers=True),
        )
        if self.work_item_id in self.depends_on:
            raise RenovationPlanError("work item cannot depend on itself")
        if self.provenance.source_revision != self.base_revision:
            raise RenovationPlanError(
                "work item base revision must match provenance source revision"
            )
        expected_inputs = (self.base_snapshot_sha256,)
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationPlanError(
                "work item provenance must bind exactly the base snapshot"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkItemContract":
        body = cls._contract_payload(payload)
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise RenovationPlanError("work item provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


@dataclass(frozen=True)
class RenovationPlan(CanonicalContract):
    """Exactly two typed WorkItems bound to one mission and base Twin."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.renovation-plan"

    plan_id: str
    mission_id: str
    mission_sha256: str
    base_revision: str
    base_snapshot_sha256: str
    work_items: tuple[WorkItemContract, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("plan_id", "mission_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "mission_sha256", _sha256(self.mission_sha256, "mission_sha256")
        )
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "base_snapshot_sha256",
            _sha256(self.base_snapshot_sha256, "base_snapshot_sha256"),
        )
        items = tuple(self.work_items)
        if any(not isinstance(item, WorkItemContract) for item in items):
            raise RenovationPlanError(
                "work_items must contain WorkItemContract records"
            )
        if len(items) != 2:
            raise RenovationPlanError(
                "Renovation ignition plan must contain exactly two work items"
            )
        if len({item.work_item_id for item in items}) != 2:
            raise RenovationPlanError("work item identifiers must be unique")
        items = tuple(sorted(items, key=lambda item: item.work_item_id))
        object.__setattr__(self, "work_items", items)

        by_kind = {item.kind: item for item in items}
        if set(by_kind) != set(_WORK_KINDS):
            raise RenovationPlanError(
                "plan must contain one symbol-rename and one representation-sync item"
            )
        if any(item.mission_id != self.mission_id for item in items):
            raise RenovationPlanError("every work item must bind the plan mission")
        if any(item.base_revision != self.base_revision for item in items):
            raise RenovationPlanError("every work item must bind the plan revision")
        if any(
            item.base_snapshot_sha256 != self.base_snapshot_sha256 for item in items
        ):
            raise RenovationPlanError("every work item must bind the base snapshot")
        covered_planes = {plane for item in items for plane in item.plane_scope}
        if covered_planes != set(FOURFOLD_PLANES):
            raise RenovationPlanError("the two work items must cover all four planes")

        rename_item = by_kind["symbol-rename"]
        sync_item = by_kind["representation-sync"]
        if rename_item.depends_on:
            raise RenovationPlanError("symbol rename must be the root work item")
        if sync_item.depends_on != (rename_item.work_item_id,):
            raise RenovationPlanError(
                "representation sync must depend exactly on the symbol rename"
            )
        rename_paths = set(rename_item.writable_paths)
        sync_paths = set(sync_item.writable_paths)
        if rename_paths.intersection(sync_paths):
            raise RenovationPlanError(
                "work item writable paths must be disjoint ownership boundaries"
            )
        if self.provenance.source_revision != self.base_revision:
            raise RenovationPlanError(
                "plan base revision must match provenance source revision"
            )
        expected_inputs = tuple(
            sorted(
                {
                    self.mission_sha256,
                    self.base_snapshot_sha256,
                    *(item.digest for item in items),
                }
            )
        )
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise RenovationPlanError(
                "plan provenance must bind exactly mission, snapshot, and work items"
            )

    @property
    def work_item_ids(self) -> tuple[str, ...]:
        return tuple(item.work_item_id for item in self.work_items)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RenovationPlan":
        body = cls._contract_payload(payload)
        raw_items = body.get("work_items")
        if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, (list, tuple)):
            raise RenovationPlanError("work_items must be an array")
        body["work_items"] = tuple(
            WorkItemContract.from_dict(item) for item in raw_items
        )
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise RenovationPlanError("plan provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


def verify_renovation_plan(
    plan: RenovationPlan,
    *,
    mission: MissionContract,
    base_snapshot: FourfoldSnapshot,
) -> RenovationPlan:
    """Recompute all external bindings before a plan may be consumed."""

    if not isinstance(plan, RenovationPlan):
        raise RenovationPlanBindingError("plan must be a RenovationPlan")
    if not isinstance(mission, MissionContract):
        raise RenovationPlanBindingError("mission must be a MissionContract")
    if not isinstance(base_snapshot, FourfoldSnapshot):
        raise RenovationPlanBindingError("base snapshot must be a FourfoldSnapshot")
    mismatches: list[str] = []
    if plan.mission_id != mission.mission_id:
        mismatches.append("mission_id")
    if plan.mission_sha256 != mission.digest:
        mismatches.append("mission_sha256")
    if plan.base_revision != mission.source_revision:
        mismatches.append("mission_source_revision")
    if plan.base_snapshot_sha256 != base_snapshot.digest:
        mismatches.append("base_snapshot_sha256")
    if plan.base_revision != base_snapshot.source_revision:
        mismatches.append("snapshot_source_revision")
    if tuple(sorted(mission.work_item_ids)) != tuple(sorted(plan.work_item_ids)):
        mismatches.append("work_item_ids")
    incomplete = sorted(
        plane.plane for plane in base_snapshot.planes if plane.status != "complete"
    )
    if incomplete:
        mismatches.append("incomplete_planes:" + ",".join(incomplete))
    if mismatches:
        raise RenovationPlanBindingError(
            "Renovation plan binding mismatch: " + ", ".join(sorted(mismatches))
        )
    return plan


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RenovationPlanError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_renovation_plan(payload: Mapping[str, Any]) -> RenovationPlan:
    """Parse only the exact canonical RenovationPlan wire representation."""

    if not isinstance(payload, Mapping):
        raise RenovationPlanError("Renovation plan must be an object")
    plan = RenovationPlan.from_dict(payload)
    if dict(payload) != plan.to_dict():
        raise RenovationPlanError("Renovation plan wire is not canonical")
    return plan


def load_renovation_plan(path: str | Path) -> RenovationPlan:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise RenovationPlanError("Renovation plan JSON root must be an object")
    return parse_renovation_plan(payload)
