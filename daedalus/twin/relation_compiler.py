"""Compile authoritative Forest/Fourfold facts into typed sparse relation blocks.

The compiler is a pure, revision-bound projection. It does not create a second
source of truth, grant trust, persist state, or promote a retrieval result. It
turns already-authoritative ``KnowledgeForest`` edges and already-verified
``FourfoldSnapshot`` bindings into the canonical ``TypedRelationBlock`` oracle
used by the contraction interpreter.

Every axis is the complete plane membership from the snapshot rather than the
labels observed in one relation. That makes independently compiled relations
exactly composable without reconstructing ad-hoc indices per query.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Mapping, Sequence, TypeVar

from ..schemas import _sha256
from ..spine.envelope import canonical_sha
from ..structcore.forest import ForestEdge, KnowledgeForest
from .contracts import FOURFOLD_PLANES, FourfoldSnapshot
from .relation_blocks import (
    MAX_BLOCK_ENTRIES,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from .semiring import (
    EvidenceValue,
    Semiring,
)

T = TypeVar("T")

MAX_COMPILED_RELATIONS = 4_096
_SUPPORTED_OBSERVERS = frozenset({"boolean", "natural", "evidence-dag"})


def relation_block_name(signature: RelationSignature) -> str:
    """Return the collision-free logical name used by ``BlockRef``."""

    if not isinstance(signature, RelationSignature):
        raise ValueError("signature must be a RelationSignature")
    return (
        f"{signature.source_plane}:{signature.relation}:"
        f"{signature.target_plane}"
    )


@dataclass(frozen=True)
class CompiledRelationBlocks(Generic[T]):
    """One deterministic relation-block projection and its compact receipt."""

    subject: ProjectionSubject
    semiring_name: str
    source_forest_sha256: str
    blocks: tuple[tuple[str, TypedRelationBlock[T]], ...]
    semantic_fact_count: int
    forest_edge_count: int
    verified_binding_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ProjectionSubject):
            raise ValueError("subject must be a ProjectionSubject")
        if self.semiring_name not in _SUPPORTED_OBSERVERS:
            raise ValueError("unsupported compiled relation observer")
        object.__setattr__(
            self,
            "source_forest_sha256",
            _sha256(self.source_forest_sha256, "source_forest_sha256"),
        )
        for name in (
            "semantic_fact_count",
            "forest_edge_count",
            "verified_binding_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

        names: set[str] = set()
        ordered: list[tuple[str, TypedRelationBlock[T]]] = []
        for name, block in tuple(self.blocks):
            if type(name) is not str or not name:
                raise ValueError("compiled block names must be non-empty strings")
            if name in names:
                raise ValueError(f"duplicate compiled block name {name!r}")
            if not isinstance(block, TypedRelationBlock):
                raise ValueError(
                    "compiled blocks must contain TypedRelationBlock values"
                )
            if block.subject != self.subject:
                raise ValueError("compiled block binds another Fourfold subject")
            if block.semiring_name != self.semiring_name:
                raise ValueError("compiled block uses another semiring")
            if relation_block_name(block.signature) != name:
                raise ValueError(
                    "compiled block name does not match its signature"
                )
            names.add(name)
            ordered.append((name, block))
        ordered.sort(key=lambda item: item[0])
        object.__setattr__(self, "blocks", tuple(ordered))
        if self.semantic_fact_count != sum(
            block.entry_count for _, block in ordered
        ):
            raise ValueError(
                "semantic_fact_count does not match compiled entries"
            )

    @property
    def block_map(self) -> Mapping[str, TypedRelationBlock[T]]:
        return MappingProxyType(dict(self.blocks))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "semiring_name": self.semiring_name,
            "source_forest_sha256": self.source_forest_sha256,
            "semantic_fact_count": self.semantic_fact_count,
            "forest_edge_count": self.forest_edge_count,
            "verified_binding_count": self.verified_binding_count,
            "blocks": [
                {
                    "name": name,
                    "signature": block.signature.to_dict(),
                    "entry_count": block.entry_count,
                    "digest": block.digest,
                }
                for name, block in self.blocks
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _selected_signatures(
    requested: Sequence[RelationSignature] | None,
    discovered: set[RelationSignature],
) -> tuple[RelationSignature, ...]:
    if requested is None:
        values = tuple(discovered)
    else:
        if isinstance(requested, (str, bytes, Mapping)):
            raise ValueError("signatures must be a bounded sequence")
        if len(requested) > MAX_COMPILED_RELATIONS:
            raise ValueError(
                f"signatures exceed bounded limit {MAX_COMPILED_RELATIONS}"
            )
        values = tuple(requested)
        if any(not isinstance(item, RelationSignature) for item in values):
            raise ValueError(
                "signatures must contain RelationSignature records"
            )
        if len(set(values)) != len(values):
            raise ValueError("signatures must not contain duplicates")
    if len(values) > MAX_COMPILED_RELATIONS:
        raise ValueError(
            f"compiled relation count exceeds limit {MAX_COMPILED_RELATIONS}"
        )
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.source_plane,
                item.relation,
                item.target_plane,
            ),
        )
    )


def _observer_name(semiring: Semiring[Any]) -> str:
    if not isinstance(semiring, Semiring):
        raise ValueError("semiring must implement the Semiring protocol")
    if semiring.name not in _SUPPORTED_OBSERVERS:
        raise ValueError(
            "Forest relation compilation supports boolean, natural and "
            "evidence-dag observers; tropical requires an explicit cost "
            "projection instead of reinterpreting ForestEdge.weight"
        )
    return semiring.name


def _record_fact(
    facts: dict[
        RelationSignature,
        dict[tuple[str, str], set[tuple[str, ...]]],
    ],
    *,
    signature: RelationSignature,
    source: str,
    target: str,
    evidence_atoms: Sequence[str],
) -> None:
    atoms = tuple(sorted(set(evidence_atoms)))
    bucket = facts.setdefault(signature, {})
    bucket.setdefault((source, target), set()).add(atoms)


def _forest_edge_atoms(edge: ForestEdge) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                canonical_sha(edge.to_dict()),
                *edge.evidence,
            }
        )
    )


def compile_relation_blocks(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    semiring: Semiring[T],
    *,
    signatures: Sequence[RelationSignature] | None = None,
    include_verified_bindings: bool = True,
) -> CompiledRelationBlocks[T]:
    """Compile selected relations under one explicit observer semiring.

    ``signatures`` may predeclare empty blocks, which is useful for frozen query
    plans. When omitted, every relation signature observed in the Forest or in
    verified cross-plane bindings is compiled.

    Forest edges and matching verified bindings are deduplicated by semantic
    endpoint/relation identity. Their evidence bundles remain alternative
    provenance paths in the evidence observer.
    """

    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    observer_name = _observer_name(semiring)
    forest_digest = forest.content_sha256
    if snapshot.source_forest_sha256 != forest_digest:
        raise ValueError("snapshot does not bind the supplied Forest digest")
    provenance_revision = forest.provenance.get("source_revision")
    if (
        provenance_revision is not None
        and provenance_revision != snapshot.source_revision
    ):
        raise ValueError(
            "Forest provenance revision differs from the snapshot"
        )

    node_plane: dict[str, str] = {}
    for plane in snapshot.planes:
        for node_id in plane.node_ids:
            node_plane[node_id] = plane.plane

    forest_node_ids = tuple(node.id for node in forest.nodes)
    if len(set(forest_node_ids)) != len(forest_node_ids):
        raise ValueError("Forest contains duplicate node ids")
    missing_nodes = sorted(set(forest_node_ids) - set(node_plane))
    if missing_nodes:
        raise ValueError(
            "Forest nodes are missing from the Fourfold plane partition: "
            + ", ".join(missing_nodes[:8])
        )

    facts: dict[
        RelationSignature,
        dict[tuple[str, str], set[tuple[str, ...]]],
    ] = {}
    for edge in forest.edges:
        source_plane = node_plane.get(edge.source)
        target_plane = node_plane.get(edge.target)
        if source_plane is None or target_plane is None:
            raise ValueError(
                f"Forest edge {edge.relation!r} references an endpoint outside "
                "the Fourfold snapshot"
            )
        signature = RelationSignature(
            source_plane,
            edge.relation,
            target_plane,
        )
        atoms = _forest_edge_atoms(edge)
        _record_fact(
            facts,
            signature=signature,
            source=edge.source,
            target=edge.target,
            evidence_atoms=atoms,
        )
        if not edge.directed and edge.source != edge.target:
            reverse = RelationSignature(
                target_plane,
                edge.relation,
                source_plane,
            )
            _record_fact(
                facts,
                signature=reverse,
                source=edge.target,
                target=edge.source,
                evidence_atoms=atoms,
            )

    binding_count = 0
    if include_verified_bindings:
        binding_count = len(snapshot.bindings)
        for binding in snapshot.bindings:
            signature = RelationSignature(
                binding.source_plane,
                binding.relation,
                binding.target_plane,
            )
            _record_fact(
                facts,
                signature=signature,
                source=binding.source_node_id,
                target=binding.target_node_id,
                evidence_atoms=(
                    binding.digest,
                    *binding.evidence_sha256s,
                ),
            )

    selected = _selected_signatures(signatures, set(facts))
    subject = ProjectionSubject(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_fourfold_sha256=snapshot.digest,
    )
    axes = {
        plane: TypedAxis(
            name=f"{plane}-nodes",
            plane=plane,
            labels=snapshot.plane_map[plane].node_ids,
        )
        for plane in FOURFOLD_PLANES
    }

    compiled: list[tuple[str, TypedRelationBlock[T]]] = []
    for signature in selected:
        coordinates: list[tuple[str, str, Any]] = []
        for (source, target), evidence_bundles in sorted(
            facts.get(signature, {}).items()
        ):
            if observer_name == "boolean":
                value: Any = True
            elif observer_name == "natural":
                value = 1
            else:
                value = EvidenceValue(tuple(sorted(evidence_bundles)))
            coordinates.append((source, target, value))
        if len(coordinates) > MAX_BLOCK_ENTRIES:
            raise ValueError(
                f"relation {relation_block_name(signature)!r} exceeds "
                f"bounded entry limit {MAX_BLOCK_ENTRIES}"
            )
        block = TypedRelationBlock.from_coordinates(
            subject=subject,
            signature=signature,
            row_axis=axes[signature.source_plane],
            column_axis=axes[signature.target_plane],
            coordinates=tuple(coordinates),
            semiring=semiring,
        )
        compiled.append((relation_block_name(signature), block))

    return CompiledRelationBlocks(
        subject=subject,
        semiring_name=observer_name,
        source_forest_sha256=forest_digest,
        blocks=tuple(compiled),
        semantic_fact_count=sum(block.entry_count for _, block in compiled),
        forest_edge_count=len(forest.edges),
        verified_binding_count=binding_count,
    )


__all__ = [
    "MAX_COMPILED_RELATIONS",
    "CompiledRelationBlocks",
    "compile_relation_blocks",
    "relation_block_name",
]
