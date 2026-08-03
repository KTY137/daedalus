"""Deterministic, non-applying deltas between two Fourfold snapshots.

A GraphDelta compares two already-built, revision-bound snapshots. It records
semantic membership changes separately from evidence changes and never mutates,
materializes, publishes or promotes either snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from ..schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _record_payload,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)
from ..spine.envelope import canonical_sha
from .contracts import FOURFOLD_PLANES, CrossPlaneBinding, FourfoldSnapshot

_PLANE_STATUSES = frozenset({"complete", "partial", "absent"})
_BINDING_CHANGE_KINDS = frozenset(
    {"added", "removed", "evidence_changed", "unchanged"}
)


def _plane(value: Any, name: str) -> str:
    if value not in FOURFOLD_PLANES:
        raise ValueError(f"{name} must be one of {FOURFOLD_PLANES}")
    return str(value)


def _status(value: Any, name: str) -> str:
    if value not in _PLANE_STATUSES:
        raise ValueError(f"{name} must be complete, partial or absent")
    return str(value)


def _node_ids(values: Any, name: str) -> tuple[str, ...]:
    return _sorted_strings(values, name)


def _digests(values: Any, name: str) -> tuple[str, ...]:
    return _sorted_strings(values, name, digests=True)


def _pairwise_disjoint(*groups: tuple[str, ...]) -> bool:
    seen: set[str] = set()
    for group in groups:
        current = set(group)
        if seen.intersection(current):
            return False
        seen.update(current)
    return True


def _binding_semantic_payload(binding: CrossPlaneBinding) -> dict[str, str]:
    return {
        "source_plane": binding.source_plane,
        "source_node_id": binding.source_node_id,
        "target_plane": binding.target_plane,
        "target_node_id": binding.target_node_id,
        "relation": binding.relation,
    }


def _binding_semantic_sha256(binding: CrossPlaneBinding) -> str:
    return canonical_sha(_binding_semantic_payload(binding))


@dataclass(frozen=True)
class PlaneDelta:
    """Set-complete membership/evidence comparison for one semantic plane."""

    plane: str
    base_plane_sha256: str
    candidate_plane_sha256: str
    base_status: str
    candidate_status: str
    added_node_ids: tuple[str, ...] = ()
    removed_node_ids: tuple[str, ...] = ()
    retained_node_ids: tuple[str, ...] = ()
    added_evidence_sha256s: tuple[str, ...] = ()
    removed_evidence_sha256s: tuple[str, ...] = ()
    retained_evidence_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "plane", _plane(self.plane, "plane"))
        for field_name in ("base_plane_sha256", "candidate_plane_sha256"):
            object.__setattr__(
                self, field_name, _sha256(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "base_status", _status(self.base_status, "base_status")
        )
        object.__setattr__(
            self,
            "candidate_status",
            _status(self.candidate_status, "candidate_status"),
        )
        for field_name in (
            "added_node_ids",
            "removed_node_ids",
            "retained_node_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _node_ids(getattr(self, field_name), field_name),
            )
        for field_name in (
            "added_evidence_sha256s",
            "removed_evidence_sha256s",
            "retained_evidence_sha256s",
        ):
            object.__setattr__(
                self,
                field_name,
                _digests(getattr(self, field_name), field_name),
            )
        if not _pairwise_disjoint(
            self.added_node_ids,
            self.removed_node_ids,
            self.retained_node_ids,
        ):
            raise ValueError("plane node partitions must be pairwise disjoint")
        if not _pairwise_disjoint(
            self.added_evidence_sha256s,
            self.removed_evidence_sha256s,
            self.retained_evidence_sha256s,
        ):
            raise ValueError("plane evidence partitions must be pairwise disjoint")
        if self.base_status == "absent" and (
            self.removed_node_ids or self.retained_node_ids
        ):
            raise ValueError("an absent base plane cannot retain or remove nodes")
        if self.candidate_status == "absent" and (
            self.added_node_ids or self.retained_node_ids
        ):
            raise ValueError("an absent candidate plane cannot add or retain nodes")

    @property
    def semantic_changed(self) -> bool:
        return bool(
            self.base_status != self.candidate_status
            or self.added_node_ids
            or self.removed_node_ids
        )

    @property
    def evidence_changed(self) -> bool:
        return bool(self.added_evidence_sha256s or self.removed_evidence_sha256s)

    @property
    def changed(self) -> bool:
        return self.semantic_changed or self.evidence_changed

    def to_dict(self) -> dict[str, Any]:
        return {
            "plane": self.plane,
            "base_plane_sha256": self.base_plane_sha256,
            "candidate_plane_sha256": self.candidate_plane_sha256,
            "base_status": self.base_status,
            "candidate_status": self.candidate_status,
            "added_node_ids": list(self.added_node_ids),
            "removed_node_ids": list(self.removed_node_ids),
            "retained_node_ids": list(self.retained_node_ids),
            "added_evidence_sha256s": list(self.added_evidence_sha256s),
            "removed_evidence_sha256s": list(self.removed_evidence_sha256s),
            "retained_evidence_sha256s": list(self.retained_evidence_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlaneDelta":
        body = _record_payload(cls, payload, "plane delta")
        for field_name in (
            "added_node_ids",
            "removed_node_ids",
            "retained_node_ids",
            "added_evidence_sha256s",
            "removed_evidence_sha256s",
            "retained_evidence_sha256s",
        ):
            value = body.get(field_name)
            if not isinstance(value, list):
                raise ValueError(f"{field_name} must be an array")
            body[field_name] = tuple(value)
        return cls(**body)


@dataclass(frozen=True)
class BindingDelta:
    """Revision-independent semantic identity with exact before/after records."""

    semantic_sha256: str
    change_kind: str
    base_binding: CrossPlaneBinding | None = None
    candidate_binding: CrossPlaneBinding | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "semantic_sha256",
            _sha256(self.semantic_sha256, "semantic_sha256"),
        )
        if self.change_kind not in _BINDING_CHANGE_KINDS:
            raise ValueError(
                f"change_kind must be one of {sorted(_BINDING_CHANGE_KINDS)}"
            )
        if self.base_binding is not None and not isinstance(
            self.base_binding, CrossPlaneBinding
        ):
            raise ValueError("base_binding must be a CrossPlaneBinding or null")
        if self.candidate_binding is not None and not isinstance(
            self.candidate_binding, CrossPlaneBinding
        ):
            raise ValueError("candidate_binding must be a CrossPlaneBinding or null")
        if self.base_binding is None and self.candidate_binding is None:
            raise ValueError("binding delta must retain at least one binding")

        reference = self.base_binding or self.candidate_binding
        assert reference is not None
        expected_semantic = _binding_semantic_sha256(reference)
        if self.semantic_sha256 != expected_semantic:
            raise ValueError("semantic_sha256 does not match binding endpoints")
        if self.base_binding is not None and (
            _binding_semantic_sha256(self.base_binding) != self.semantic_sha256
        ):
            raise ValueError("base binding semantic identity mismatch")
        if self.candidate_binding is not None and (
            _binding_semantic_sha256(self.candidate_binding) != self.semantic_sha256
        ):
            raise ValueError("candidate binding semantic identity mismatch")

        if self.base_binding is None:
            derived = "added"
        elif self.candidate_binding is None:
            derived = "removed"
        elif (
            self.base_binding.evidence_sha256s
            != self.candidate_binding.evidence_sha256s
        ):
            derived = "evidence_changed"
        else:
            derived = "unchanged"
        if self.change_kind != derived:
            raise ValueError(
                f"change_kind must be derived from retained bindings: {derived}"
            )

    @property
    def semantic_changed(self) -> bool:
        return self.change_kind in {"added", "removed"}

    @property
    def evidence_changed(self) -> bool:
        return self.change_kind == "evidence_changed"

    @property
    def changed(self) -> bool:
        return self.semantic_changed or self.evidence_changed

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_sha256": self.semantic_sha256,
            "change_kind": self.change_kind,
            "base_binding": (
                None if self.base_binding is None else self.base_binding.to_dict()
            ),
            "candidate_binding": (
                None
                if self.candidate_binding is None
                else self.candidate_binding.to_dict()
            ),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BindingDelta":
        body = _record_payload(cls, payload, "binding delta")
        for field_name in ("base_binding", "candidate_binding"):
            value = body.get(field_name)
            if value is not None:
                if not isinstance(value, Mapping):
                    raise ValueError(f"{field_name} must be an object or null")
                body[field_name] = CrossPlaneBinding.from_dict(value)
        return cls(**body)


@dataclass(frozen=True)
class GraphDelta(CanonicalContract):
    """Exact, deterministic comparison of two FourfoldSnapshot identities."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.graph-delta"

    repository_id: str
    base_snapshot_sha256: str
    candidate_snapshot_sha256: str
    base_revision: str
    candidate_revision: str
    plane_deltas: tuple[PlaneDelta, ...]
    binding_deltas: tuple[BindingDelta, ...]
    semantic_changed: bool
    evidence_changed: bool
    changed: bool
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _identifier(self.repository_id, "repository_id")
        )
        for field_name in (
            "base_snapshot_sha256",
            "candidate_snapshot_sha256",
        ):
            object.__setattr__(
                self, field_name, _sha256(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "candidate_revision",
            _revision(self.candidate_revision, "candidate_revision"),
        )
        if not isinstance(self.plane_deltas, tuple):
            object.__setattr__(self, "plane_deltas", tuple(self.plane_deltas))
        if len(self.plane_deltas) != len(FOURFOLD_PLANES) or any(
            not isinstance(item, PlaneDelta) for item in self.plane_deltas
        ):
            raise ValueError("graph delta must contain exactly four PlaneDelta records")
        if tuple(item.plane for item in self.plane_deltas) != FOURFOLD_PLANES:
            raise ValueError("plane deltas must use canonical Fourfold plane order")

        if not isinstance(self.binding_deltas, tuple):
            object.__setattr__(self, "binding_deltas", tuple(self.binding_deltas))
        if any(not isinstance(item, BindingDelta) for item in self.binding_deltas):
            raise ValueError("binding_deltas must contain BindingDelta records")
        binding_keys = tuple(item.semantic_sha256 for item in self.binding_deltas)
        if binding_keys != tuple(sorted(set(binding_keys))):
            raise ValueError(
                "binding_deltas must be unique and sorted by semantic_sha256"
            )
        for item in self.binding_deltas:
            if item.base_binding is not None and (
                item.base_binding.source_revision != self.base_revision
            ):
                raise ValueError("base binding revision mismatch")
            if item.candidate_binding is not None and (
                item.candidate_binding.source_revision != self.candidate_revision
            ):
                raise ValueError("candidate binding revision mismatch")

        for field_name in ("semantic_changed", "evidence_changed", "changed"):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be an exact boolean")
        derived_semantic = any(item.semantic_changed for item in self.plane_deltas) or any(
            item.semantic_changed for item in self.binding_deltas
        )
        derived_evidence = any(item.evidence_changed for item in self.plane_deltas) or any(
            item.evidence_changed for item in self.binding_deltas
        )
        if self.semantic_changed is not derived_semantic:
            raise ValueError("semantic_changed must be derived from delta records")
        if self.evidence_changed is not derived_evidence:
            raise ValueError("evidence_changed must be derived from delta records")
        if self.changed is not (derived_semantic or derived_evidence):
            raise ValueError("changed must be derived from semantic/evidence changes")
        if self.provenance.source_revision != self.candidate_revision:
            raise ValueError("graph delta provenance must use candidate_revision")
        _require_provenance_inputs(
            self.provenance,
            (
                self.base_snapshot_sha256,
                self.candidate_snapshot_sha256,
                *(item.digest for item in self.plane_deltas),
                *(item.digest for item in self.binding_deltas),
            ),
            "graph delta",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "repository_id": self.repository_id,
            "base_snapshot_sha256": self.base_snapshot_sha256,
            "candidate_snapshot_sha256": self.candidate_snapshot_sha256,
            "base_revision": self.base_revision,
            "candidate_revision": self.candidate_revision,
            "plane_deltas": [item.to_dict() for item in self.plane_deltas],
            "binding_deltas": [item.to_dict() for item in self.binding_deltas],
            "semantic_changed": self.semantic_changed,
            "evidence_changed": self.evidence_changed,
            "changed": self.changed,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GraphDelta":
        body = cls._contract_payload(payload)
        plane_deltas = body.get("plane_deltas")
        binding_deltas = body.get("binding_deltas")
        if not isinstance(plane_deltas, list):
            raise ValueError("graph delta plane_deltas must be an array")
        if not isinstance(binding_deltas, list):
            raise ValueError("graph delta binding_deltas must be an array")
        if not isinstance(body.get("provenance"), Mapping):
            raise ValueError("graph delta provenance must be an object")
        body["plane_deltas"] = tuple(
            PlaneDelta.from_dict(item) for item in plane_deltas
        )
        body["binding_deltas"] = tuple(
            BindingDelta.from_dict(item) for item in binding_deltas
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def compute_graph_delta(
    base: FourfoldSnapshot,
    candidate: FourfoldSnapshot,
    *,
    created_at: str,
    trace_id: str | None = None,
) -> GraphDelta:
    """Compare two snapshots without mutating or applying either one."""

    if not isinstance(base, FourfoldSnapshot) or not isinstance(
        candidate, FourfoldSnapshot
    ):
        raise ValueError("base and candidate must be FourfoldSnapshot records")
    if base.repository_id != candidate.repository_id:
        raise ValueError("graph delta snapshots must belong to the same repository")

    base_planes = base.plane_map
    candidate_planes = candidate.plane_map
    plane_deltas: list[PlaneDelta] = []
    for plane in FOURFOLD_PLANES:
        before = base_planes[plane]
        after = candidate_planes[plane]
        before_nodes = set(before.node_ids)
        after_nodes = set(after.node_ids)
        before_evidence = set(before.evidence_sha256s)
        after_evidence = set(after.evidence_sha256s)
        plane_deltas.append(
            PlaneDelta(
                plane=plane,
                base_plane_sha256=before.digest,
                candidate_plane_sha256=after.digest,
                base_status=before.status,
                candidate_status=after.status,
                added_node_ids=tuple(after_nodes - before_nodes),
                removed_node_ids=tuple(before_nodes - after_nodes),
                retained_node_ids=tuple(before_nodes & after_nodes),
                added_evidence_sha256s=tuple(after_evidence - before_evidence),
                removed_evidence_sha256s=tuple(before_evidence - after_evidence),
                retained_evidence_sha256s=tuple(before_evidence & after_evidence),
            )
        )

    base_bindings = {
        _binding_semantic_sha256(item): item for item in base.bindings
    }
    candidate_bindings = {
        _binding_semantic_sha256(item): item for item in candidate.bindings
    }
    binding_deltas: list[BindingDelta] = []
    for semantic_sha in sorted(set(base_bindings) | set(candidate_bindings)):
        before = base_bindings.get(semantic_sha)
        after = candidate_bindings.get(semantic_sha)
        if before is None:
            change_kind = "added"
        elif after is None:
            change_kind = "removed"
        elif before.evidence_sha256s != after.evidence_sha256s:
            change_kind = "evidence_changed"
        else:
            change_kind = "unchanged"
        binding_deltas.append(
            BindingDelta(
                semantic_sha256=semantic_sha,
                change_kind=change_kind,
                base_binding=before,
                candidate_binding=after,
            )
        )

    plane_tuple = tuple(plane_deltas)
    binding_tuple = tuple(binding_deltas)
    semantic_changed = any(item.semantic_changed for item in plane_tuple) or any(
        item.semantic_changed for item in binding_tuple
    )
    evidence_changed = any(item.evidence_changed for item in plane_tuple) or any(
        item.evidence_changed for item in binding_tuple
    )
    provenance = ContractProvenance(
        origin="daedalus.twin.graph-delta",
        source_revision=candidate.source_revision,
        created_at=created_at,
        input_digests=(
            base.digest,
            candidate.digest,
            *(item.digest for item in plane_tuple),
            *(item.digest for item in binding_tuple),
        ),
        trace_id=trace_id,
    )
    return GraphDelta(
        repository_id=base.repository_id,
        base_snapshot_sha256=base.digest,
        candidate_snapshot_sha256=candidate.digest,
        base_revision=base.source_revision,
        candidate_revision=candidate.source_revision,
        plane_deltas=plane_tuple,
        binding_deltas=binding_tuple,
        semantic_changed=semantic_changed,
        evidence_changed=evidence_changed,
        changed=semantic_changed or evidence_changed,
        provenance=provenance,
    )


def require_graph_delta(
    delta: GraphDelta,
    base: FourfoldSnapshot,
    candidate: FourfoldSnapshot,
) -> None:
    """Recompute a submitted delta against exact snapshots before consumption."""

    if not isinstance(delta, GraphDelta):
        raise ValueError("delta must be a GraphDelta")
    expected = compute_graph_delta(
        base,
        candidate,
        created_at=delta.provenance.created_at,
        trace_id=delta.provenance.trace_id,
    )
    if delta != expected:
        raise ValueError("graph delta does not match recomputed snapshot comparison")


def parse_graph_delta(payload: Mapping[str, Any]) -> GraphDelta:
    value = GraphDelta.from_dict(payload)
    if dict(payload) != value.to_dict():
        raise ValueError("graph delta wire is not canonical")
    return value


__all__ = [
    "BindingDelta",
    "GraphDelta",
    "PlaneDelta",
    "compute_graph_delta",
    "parse_graph_delta",
    "require_graph_delta",
]
