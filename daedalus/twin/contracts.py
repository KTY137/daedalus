"""Canonical contracts for one revision-bound Fourfold Project Twin.

This module supplies semantic contracts, not a second graph authority. Source
and candidate trees remain authoritative artifacts and KnowledgeForest remains
the current compiled graph IR. A :class:`FourfoldSnapshot` partitions evidence
from one exact revision into the four constitutional planes and retains only
independently verified cross-plane bindings.

LLM or embedding output must not be placed directly in ``bindings``. Proposal
contracts belong to a later, separate boundary because proposal and verified
fact have different authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, Sequence

from ..schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _non_empty,
    _record_payload,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)
from ..spine.envelope import canonical_sha

FOURFOLD_PLANES = ("code", "type", "data", "knowledge")
_PLANE_SET = frozenset(FOURFOLD_PLANES)
_PLANE_STATUSES = frozenset({"complete", "partial", "absent"})


def _node_id(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=2000)
    if "\x00" in text:
        raise ValueError(f"{name} contains a NUL byte")
    return text


def _sorted_node_ids(values: Sequence[Any], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence, not a string")

    converted: list[str] = []
    in_order = True
    previous: str | None = None
    for index, value in enumerate(values):
        node_id = _node_id(value, f"{name}[{index}]")
        if previous is not None:
            if node_id == previous:
                raise ValueError(f"{name} must not contain duplicates")
            if node_id < previous:
                in_order = False
        converted.append(node_id)
        previous = node_id

    if in_order:
        if type(values) is tuple:
            return values
        return tuple(converted)

    converted.sort()
    for index in range(1, len(converted)):
        if converted[index - 1] == converted[index]:
            raise ValueError(f"{name} must not contain duplicates")
    return tuple(converted)


@dataclass(frozen=True)
class PlaneSnapshot:
    """The evidence membership of one semantic plane at one exact revision.

    ``relation_sha256s`` identify canonical ForestEdge/ForestHyperedge payloads;
    they do not create a second edge schema. ``absent`` is explicit and must
    carry a reason. This prevents a missing extractor from masquerading as a
    successfully empty plane.
    """

    plane: str
    source_revision: str
    status: str
    node_ids: tuple[str, ...] = ()
    relation_sha256s: tuple[str, ...] = ()
    evidence_sha256s: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.plane not in _PLANE_SET:
            raise ValueError(
                f"plane must be one of {FOURFOLD_PLANES}, got {self.plane!r}"
            )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "plane.source_revision"),
        )
        if self.status not in _PLANE_STATUSES:
            raise ValueError("plane.status must be complete, partial, or absent")
        object.__setattr__(
            self,
            "node_ids",
            _sorted_node_ids(self.node_ids, "plane.node_ids"),
        )
        object.__setattr__(
            self,
            "relation_sha256s",
            _sorted_strings(
                self.relation_sha256s,
                "plane.relation_sha256s",
                digests=True,
            ),
        )
        object.__setattr__(
            self,
            "evidence_sha256s",
            _sorted_strings(
                self.evidence_sha256s,
                "plane.evidence_sha256s",
                digests=True,
            ),
        )
        if self.reason:
            object.__setattr__(
                self,
                "reason",
                _non_empty(self.reason, "plane.reason", max_length=2000),
            )
        if self.status == "absent":
            if self.node_ids or self.relation_sha256s:
                raise ValueError("an absent plane cannot contain nodes or relations")
            if not self.reason:
                raise ValueError("an absent plane must retain a reason")
        elif self.status == "partial" and not self.reason:
            raise ValueError("a partial plane must explain what is incomplete")
        elif self.status == "complete":
            if self.reason:
                raise ValueError(
                    "a complete plane must not carry an incompleteness reason"
                )
            if not self.node_ids:
                raise ValueError("a complete plane must contain at least one node")
        if self.status != "absent" and not self.evidence_sha256s:
            raise ValueError("a present plane must retain evidence digests")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plane": self.plane,
            "source_revision": self.source_revision,
            "status": self.status,
            "node_ids": list(self.node_ids),
            "relation_sha256s": list(self.relation_sha256s),
            "evidence_sha256s": list(self.evidence_sha256s),
            "reason": self.reason,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlaneSnapshot":
        return cls(**_record_payload(cls, payload, "fourfold plane"))


@dataclass(frozen=True)
class CrossPlaneBinding:
    """One verified semantic relation between two different planes."""

    source_plane: str
    source_node_id: str
    target_plane: str
    target_node_id: str
    relation: str
    source_revision: str
    evidence_sha256s: tuple[str, ...]
    assurance: str = "verified"

    def __post_init__(self) -> None:
        if self.source_plane not in _PLANE_SET or self.target_plane not in _PLANE_SET:
            raise ValueError(
                f"binding planes must be members of {FOURFOLD_PLANES}"
            )
        if self.source_plane == self.target_plane:
            raise ValueError(
                "cross-plane binding endpoints must be in different planes"
            )
        object.__setattr__(
            self,
            "source_node_id",
            _node_id(self.source_node_id, "binding.source_node_id"),
        )
        object.__setattr__(
            self,
            "target_node_id",
            _node_id(self.target_node_id, "binding.target_node_id"),
        )
        object.__setattr__(
            self,
            "relation",
            _identifier(self.relation, "binding.relation"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "binding.source_revision"),
        )
        object.__setattr__(
            self,
            "evidence_sha256s",
            _sorted_strings(
                self.evidence_sha256s,
                "binding.evidence_sha256s",
                digests=True,
            ),
        )
        if not self.evidence_sha256s:
            raise ValueError(
                "verified cross-plane binding requires evidence digests"
            )
        if self.assurance != "verified":
            raise ValueError(
                "FourfoldSnapshot accepts only verified bindings; proposals are separate"
            )

    @property
    def semantic_key(self) -> tuple[str, str, str, str, str, str]:
        """Identity of the semantic claim, independent of evidence packaging."""

        return (
            self.source_plane,
            self.source_node_id,
            self.target_plane,
            self.target_node_id,
            self.relation,
            self.source_revision,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_plane": self.source_plane,
            "source_node_id": self.source_node_id,
            "target_plane": self.target_plane,
            "target_node_id": self.target_node_id,
            "relation": self.relation,
            "source_revision": self.source_revision,
            "evidence_sha256s": list(self.evidence_sha256s),
            "assurance": self.assurance,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossPlaneBinding":
        return cls(**_record_payload(cls, payload, "cross-plane binding"))


@dataclass(frozen=True)
class FourfoldSnapshot(CanonicalContract):
    """Atomic semantic view of one repository revision across all four planes."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.fourfold-snapshot"

    repository_id: str
    source_revision: str
    source_forest_sha256: str
    planes: tuple[PlaneSnapshot, ...]
    bindings: tuple[CrossPlaneBinding, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _identifier(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "source_forest_sha256",
            _sha256(self.source_forest_sha256, "source_forest_sha256"),
        )
        if not isinstance(self.planes, tuple):
            object.__setattr__(self, "planes", tuple(self.planes))
        by_name: dict[str, PlaneSnapshot] = {}
        all_node_ids: set[str] = set()
        for plane in self.planes:
            if not isinstance(plane, PlaneSnapshot):
                raise ValueError("planes must contain PlaneSnapshot records")
            if plane.plane in by_name:
                raise ValueError(f"duplicate fourfold plane {plane.plane!r}")
            if plane.source_revision != self.source_revision:
                raise ValueError(
                    "every plane must bind the FourfoldSnapshot source_revision"
                )
            repeated = sorted(all_node_ids.intersection(plane.node_ids))
            if repeated:
                raise ValueError(
                    "node ids must belong to exactly one plane; "
                    f"repeated={repeated}"
                )
            all_node_ids.update(plane.node_ids)
            by_name[plane.plane] = plane
        missing = sorted(_PLANE_SET - set(by_name))
        extra = sorted(set(by_name) - _PLANE_SET)
        if missing or extra:
            raise ValueError(
                "planes must exactly cover Fourfold planes "
                f"(missing={missing}, extra={extra})"
            )
        object.__setattr__(
            self,
            "planes",
            tuple(by_name[name] for name in FOURFOLD_PLANES),
        )

        if not isinstance(self.bindings, tuple):
            object.__setattr__(self, "bindings", tuple(self.bindings))
        node_membership = {
            plane.plane: set(plane.node_ids) for plane in self.planes
        }
        unique_by_digest: dict[str, CrossPlaneBinding] = {}
        semantic_claims: set[tuple[str, str, str, str, str, str]] = set()
        for binding in self.bindings:
            if not isinstance(binding, CrossPlaneBinding):
                raise ValueError(
                    "bindings must contain CrossPlaneBinding records"
                )
            if binding.source_revision != self.source_revision:
                raise ValueError(
                    "every binding must bind the FourfoldSnapshot source_revision"
                )
            if binding.source_node_id not in node_membership[binding.source_plane]:
                raise ValueError(
                    "binding source endpoint is not a member of its declared plane"
                )
            if binding.target_node_id not in node_membership[binding.target_plane]:
                raise ValueError(
                    "binding target endpoint is not a member of its declared plane"
                )
            semantic_key = binding.semantic_key
            if semantic_key in semantic_claims:
                raise ValueError(
                    "bindings must not repeat the same semantic claim with a "
                    "different evidence bundle"
                )
            semantic_claims.add(semantic_key)
            binding_digest = binding.digest
            if binding_digest in unique_by_digest:
                raise ValueError("bindings must not contain duplicates")
            unique_by_digest[binding_digest] = binding
        ordered_bindings = sorted(unique_by_digest.items(), key=lambda item: item[0])
        object.__setattr__(
            self,
            "bindings",
            tuple(binding for _, binding in ordered_bindings),
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "snapshot source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.source_forest_sha256,
                *(plane.digest for plane in self.planes),
                *(binding_digest for binding_digest, _ in ordered_bindings),
            ),
            "fourfold snapshot",
        )

    @property
    def plane_map(self) -> Mapping[str, PlaneSnapshot]:
        return MappingProxyType({plane.plane: plane for plane in self.planes})

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FourfoldSnapshot":
        body = cls._contract_payload(payload)
        body["planes"] = tuple(
            PlaneSnapshot.from_dict(item) for item in body["planes"]
        )
        body["bindings"] = tuple(
            CrossPlaneBinding.from_dict(item) for item in body["bindings"]
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def parse_fourfold_snapshot(payload: Mapping[str, Any]) -> FourfoldSnapshot:
    """Strict parser kept separate until the Gate-0 kernel registry is amended."""

    return FourfoldSnapshot.from_dict(payload)
