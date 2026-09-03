"""Revision-bound typed relation blocks for the hybrid retrieval experiment.

The compiler turns the existing authoritative ``KnowledgeForest`` and
``FourfoldSnapshot`` into deterministic, regenerable adjacency blocks.  The
blocks are physical query indices only: they do not become a graph authority,
verify new evidence, or promote retrieval proposals.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, KnowledgeForest
from daedalus.twin import FOURFOLD_PLANES, FourfoldSnapshot

MAX_RELATION_BLOCKS = 4_096
MAX_RELATION_ENTRIES = 1_000_000
MAX_AXIS_LABELS = 250_000

_RELATION = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any, name: str, *, max_length: int = 2_000) -> str:
    if type(value) is not str or not value or len(value) > max_length:
        raise ValueError(f"{name} must be non-empty text up to {max_length} characters")
    if "\x00" in value:
        raise ValueError(f"{name} contains a NUL byte")
    return value


def _digest(value: Any, name: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _plane(value: Any, name: str) -> str:
    if value not in FOURFOLD_PLANES:
        raise ValueError(f"{name} must be one of {FOURFOLD_PLANES}")
    return value


def _labels(values: Sequence[Any], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a bounded sequence")
    if len(values) > MAX_AXIS_LABELS:
        raise ValueError(f"{name} exceeds {MAX_AXIS_LABELS} labels")
    converted = tuple(_text(value, f"{name}[{index}]") for index, value in enumerate(values))
    if len(set(converted)) != len(converted):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(converted))


@dataclass(frozen=True)
class ProjectionSubject:
    repository_id: str
    source_revision: str
    source_forest_sha256: str
    source_fourfold_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _text(self.repository_id, "subject.repository_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _text(self.source_revision, "subject.source_revision", max_length=256),
        )
        object.__setattr__(
            self,
            "source_forest_sha256",
            _digest(self.source_forest_sha256, "subject.source_forest_sha256"),
        )
        object.__setattr__(
            self,
            "source_fourfold_sha256",
            _digest(self.source_fourfold_sha256, "subject.source_fourfold_sha256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "repository_id": self.repository_id,
            "source_revision": self.source_revision,
            "source_forest_sha256": self.source_forest_sha256,
            "source_fourfold_sha256": self.source_fourfold_sha256,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True, order=True)
class RelationSignature:
    source_plane: str
    relation: str
    target_plane: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_plane",
            _plane(self.source_plane, "signature.source_plane"),
        )
        if type(self.relation) is not str or not _RELATION.fullmatch(self.relation):
            raise ValueError("signature.relation must be a bounded relation identifier")
        object.__setattr__(
            self,
            "target_plane",
            _plane(self.target_plane, "signature.target_plane"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_plane": self.source_plane,
            "relation": self.relation,
            "target_plane": self.target_plane,
        }


@dataclass(frozen=True)
class RelationCell:
    source_node_id: str
    target_node_id: str
    evidence_sha256s: tuple[str, ...]
    weight: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_node_id",
            _text(self.source_node_id, "cell.source_node_id"),
        )
        object.__setattr__(
            self,
            "target_node_id",
            _text(self.target_node_id, "cell.target_node_id"),
        )
        if isinstance(self.evidence_sha256s, (str, bytes, Mapping)) or not isinstance(
            self.evidence_sha256s, Sequence
        ):
            raise ValueError("cell.evidence_sha256s must be a sequence")
        evidence = tuple(
            sorted(
                {
                    _digest(value, f"cell.evidence_sha256s[{index}]")
                    for index, value in enumerate(self.evidence_sha256s)
                }
            )
        )
        if not evidence:
            raise ValueError("relation cells require at least one evidence digest")
        object.__setattr__(self, "evidence_sha256s", evidence)
        if isinstance(self.weight, bool) or type(self.weight) not in (int, float):
            raise ValueError("cell.weight must be a positive finite number")
        weight = float(self.weight)
        if not math.isfinite(weight) or weight <= 0.0:
            raise ValueError("cell.weight must be a positive finite number")
        object.__setattr__(self, "weight", weight)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "evidence_sha256s": list(self.evidence_sha256s),
            "weight": self.weight,
        }


@dataclass(frozen=True)
class TypedRelationBlock:
    """One relation family compiled as a deterministic many-to-many index."""

    subject: ProjectionSubject
    signature: RelationSignature
    source_labels: tuple[str, ...]
    target_labels: tuple[str, ...]
    cells: tuple[RelationCell, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ProjectionSubject):
            raise ValueError("block.subject must be ProjectionSubject")
        if not isinstance(self.signature, RelationSignature):
            raise ValueError("block.signature must be RelationSignature")
        source_labels = _labels(self.source_labels, "block.source_labels")
        target_labels = _labels(self.target_labels, "block.target_labels")
        object.__setattr__(self, "source_labels", source_labels)
        object.__setattr__(self, "target_labels", target_labels)

        if isinstance(self.cells, (str, bytes, Mapping)) or not isinstance(self.cells, Sequence):
            raise ValueError("block.cells must be a bounded sequence")
        if len(self.cells) > MAX_RELATION_ENTRIES:
            raise ValueError(f"block.cells exceeds {MAX_RELATION_ENTRIES} entries")
        source_set, target_set = set(source_labels), set(target_labels)
        unique: dict[tuple[str, str], RelationCell] = {}
        for index, cell in enumerate(self.cells):
            if not isinstance(cell, RelationCell):
                raise ValueError(f"block.cells[{index}] must be RelationCell")
            if cell.source_node_id not in source_set:
                raise ValueError("relation cell source is outside the source-plane axis")
            if cell.target_node_id not in target_set:
                raise ValueError("relation cell target is outside the target-plane axis")
            key = (cell.source_node_id, cell.target_node_id)
            if key in unique:
                raise ValueError("relation block must not contain duplicate endpoint pairs")
            unique[key] = cell
        object.__setattr__(
            self,
            "cells",
            tuple(unique[key] for key in sorted(unique)),
        )

    @property
    def entry_count(self) -> int:
        return len(self.cells)

    def neighbors(self, node_id: str, *, direction: str = "forward") -> tuple[RelationCell, ...]:
        """Reference lookup; the physical planner builds reusable hash indices."""

        if direction == "forward":
            return tuple(cell for cell in self.cells if cell.source_node_id == node_id)
        if direction == "reverse":
            return tuple(cell for cell in self.cells if cell.target_node_id == node_id)
        raise ValueError("direction must be forward or reverse")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "signature": self.signature.to_dict(),
            "source_labels": list(self.source_labels),
            "target_labels": list(self.target_labels),
            "cells": [cell.to_dict() for cell in self.cells],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class RelationBlockCatalog:
    subject: ProjectionSubject
    node_planes: tuple[tuple[str, str], ...]
    blocks: tuple[TypedRelationBlock, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ProjectionSubject):
            raise ValueError("catalog.subject must be ProjectionSubject")
        if isinstance(self.node_planes, (str, bytes, Mapping)) or not isinstance(
            self.node_planes, Sequence
        ):
            raise ValueError("catalog.node_planes must be a sequence")
        normalized_nodes: dict[str, str] = {}
        for index, item in enumerate(self.node_planes):
            if (
                isinstance(item, (str, bytes, Mapping))
                or not isinstance(item, Sequence)
                or len(item) != 2
            ):
                raise ValueError(f"catalog.node_planes[{index}] must be (node_id, plane)")
            node_id = _text(item[0], f"catalog.node_planes[{index}].node_id")
            plane = _plane(item[1], f"catalog.node_planes[{index}].plane")
            if node_id in normalized_nodes:
                raise ValueError("catalog.node_planes must not repeat a node")
            normalized_nodes[node_id] = plane
        object.__setattr__(self, "node_planes", tuple(sorted(normalized_nodes.items())))

        if isinstance(self.blocks, (str, bytes, Mapping)) or not isinstance(self.blocks, Sequence):
            raise ValueError("catalog.blocks must be a bounded sequence")
        if len(self.blocks) > MAX_RELATION_BLOCKS:
            raise ValueError(f"catalog.blocks exceeds {MAX_RELATION_BLOCKS} blocks")
        by_signature: dict[RelationSignature, TypedRelationBlock] = {}
        for index, block in enumerate(self.blocks):
            if not isinstance(block, TypedRelationBlock):
                raise ValueError(f"catalog.blocks[{index}] must be TypedRelationBlock")
            if block.subject != self.subject:
                raise ValueError("every relation block must bind the catalog subject")
            if block.signature in by_signature:
                raise ValueError("catalog must not repeat a relation signature")
            by_signature[block.signature] = block
        object.__setattr__(
            self,
            "blocks",
            tuple(by_signature[key] for key in sorted(by_signature)),
        )

    @property
    def by_signature(self) -> Mapping[RelationSignature, TypedRelationBlock]:
        return MappingProxyType({block.signature: block for block in self.blocks})

    @property
    def node_plane_map(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.node_planes))

    def plane_of(self, node_id: str) -> str:
        try:
            return dict(self.node_planes)[node_id]
        except KeyError as exc:
            raise ValueError(f"unknown catalog node {node_id!r}") from exc

    def require(self, signature: RelationSignature) -> TypedRelationBlock:
        try:
            return self.by_signature[signature]
        except KeyError as exc:
            raise ValueError(
                "relation block is not available for "
                f"{signature.source_plane}:{signature.relation}:{signature.target_plane}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "node_planes": [[node_id, plane] for node_id, plane in self.node_planes],
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass
class _CellAccumulator:
    evidence: set[str]
    contributors: set[str]
    weight: float = 0.0


def _include_relation(relation: str, include_relations: frozenset[str] | None) -> bool:
    return include_relations is None or relation in include_relations


def compile_relation_blocks(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    *,
    include_relations: Iterable[str] | None = None,
) -> RelationBlockCatalog:
    """Compile verified Forest/Fourfold relations into deterministic typed blocks.

    Forest edges remain the structural source.  ``snapshot.bindings`` add the
    verified evidence bundle for cross-plane claims and can supply a verified
    relation absent from the legacy edge list.  Repeated representations of the
    same semantic edge merge evidence without double-counting its weight.
    """

    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    if forest.content_sha256 != snapshot.source_forest_sha256:
        raise ValueError("Forest content digest does not match FourfoldSnapshot")

    relation_filter: frozenset[str] | None = None
    if include_relations is not None:
        if isinstance(include_relations, (str, bytes, Mapping)):
            raise ValueError("include_relations must be an iterable of relation names")
        relation_filter = frozenset(
            _text(value, "include_relations[]", max_length=200)
            for value in include_relations
        )

    node_planes: dict[str, str] = {}
    labels_by_plane: dict[str, tuple[str, ...]] = {}
    for plane in snapshot.planes:
        labels_by_plane[plane.plane] = tuple(plane.node_ids)
        for node_id in plane.node_ids:
            if node_id in node_planes:
                raise ValueError("FourfoldSnapshot repeats a node across planes")
            node_planes[node_id] = plane.plane

    forest_node_ids = {node.id for node in forest.nodes}
    if len(forest_node_ids) != len(forest.nodes):
        raise ValueError("Forest contains duplicate node IDs")
    missing = sorted(forest_node_ids - set(node_planes))
    if missing:
        raise ValueError(
            "FourfoldSnapshot omits Forest nodes; refusing a lossy relation projection: "
            + ", ".join(missing[:5])
        )

    subject = ProjectionSubject(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        source_fourfold_sha256=snapshot.digest,
    )
    accumulators: dict[
        RelationSignature,
        dict[tuple[str, str], _CellAccumulator],
    ] = defaultdict(dict)

    def add(
        signature: RelationSignature,
        source_node_id: str,
        target_node_id: str,
        *,
        evidence: Iterable[str],
        contributor: str,
        weight: float | None,
    ) -> None:
        bucket = accumulators[signature]
        key = (source_node_id, target_node_id)
        item = bucket.get(key)
        if item is None:
            item = _CellAccumulator(set(), set())
            bucket[key] = item
        item.evidence.update(evidence)
        if weight is not None and contributor not in item.contributors:
            item.weight += weight
            item.contributors.add(contributor)

    def add_forest_edge(edge: ForestEdge, source: str, target: str) -> None:
        source_plane = node_planes.get(source)
        target_plane = node_planes.get(target)
        if source_plane is None or target_plane is None:
            raise ValueError(f"Forest relation {edge.relation!r} has an unknown endpoint")
        if not _include_relation(edge.relation, relation_filter):
            return
        edge_digest = canonical_sha(edge.to_dict())
        weight = float(edge.weight)
        if not math.isfinite(weight) or weight <= 0.0:
            raise ValueError("Forest relation weights must be positive and finite")
        signature = RelationSignature(source_plane, edge.relation, target_plane)
        add(
            signature,
            source,
            target,
            evidence=(forest.content_sha256, edge_digest),
            contributor=edge_digest,
            weight=weight,
        )

    for edge in forest.edges:
        add_forest_edge(edge, edge.source, edge.target)
        if not edge.directed and edge.source != edge.target:
            add_forest_edge(edge, edge.target, edge.source)

    for binding in snapshot.bindings:
        if not _include_relation(binding.relation, relation_filter):
            continue
        signature = RelationSignature(
            binding.source_plane,
            binding.relation,
            binding.target_plane,
        )
        key = (binding.source_node_id, binding.target_node_id)
        already_present = key in accumulators.get(signature, {})
        add(
            signature,
            binding.source_node_id,
            binding.target_node_id,
            evidence=(*binding.evidence_sha256s, binding.digest),
            contributor="binding:" + binding.digest,
            weight=None if already_present else 1.0,
        )

    total_entries = sum(len(cells) for cells in accumulators.values())
    if total_entries > MAX_RELATION_ENTRIES:
        raise ValueError(
            f"compiled relation entries exceed {MAX_RELATION_ENTRIES}: {total_entries}"
        )
    if len(accumulators) > MAX_RELATION_BLOCKS:
        raise ValueError(
            f"compiled relation blocks exceed {MAX_RELATION_BLOCKS}: {len(accumulators)}"
        )

    blocks: list[TypedRelationBlock] = []
    for signature in sorted(accumulators):
        cells: list[RelationCell] = []
        for (source, target), item in sorted(accumulators[signature].items()):
            cells.append(
                RelationCell(
                    source_node_id=source,
                    target_node_id=target,
                    evidence_sha256s=tuple(item.evidence),
                    weight=item.weight or 1.0,
                )
            )
        blocks.append(
            TypedRelationBlock(
                subject=subject,
                signature=signature,
                source_labels=labels_by_plane[signature.source_plane],
                target_labels=labels_by_plane[signature.target_plane],
                cells=tuple(cells),
            )
        )

    return RelationBlockCatalog(
        subject=subject,
        node_planes=tuple(node_planes.items()),
        blocks=tuple(blocks),
    )


__all__ = [
    "MAX_AXIS_LABELS",
    "MAX_RELATION_BLOCKS",
    "MAX_RELATION_ENTRIES",
    "ProjectionSubject",
    "RelationBlockCatalog",
    "RelationCell",
    "RelationSignature",
    "TypedRelationBlock",
    "compile_relation_blocks",
]
