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

from ..kernel.contracts.base import _sha256
from ..spine.envelope import canonical_sha
from ..structcore.forest import KnowledgeForest
from .contracts import CrossPlaneBinding, FOURFOLD_PLANES, FourfoldSnapshot
from .projection_verifier import _forest_node_partition
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
    forest_hyperedge_count: int
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
            "forest_hyperedge_count",
            "verified_binding_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

        if isinstance(self.blocks, (str, bytes, Mapping)) or not isinstance(
            self.blocks, Sequence
        ):
            raise ValueError("blocks must be a bounded sequence")
        block_count = len(self.blocks)
        if block_count > MAX_COMPILED_RELATIONS:
            raise ValueError(
                f"compiled block count exceeds limit {MAX_COMPILED_RELATIONS}"
            )

        names: set[str] = set()
        ordered: list[tuple[str, TypedRelationBlock[T]]] = []
        for index in range(block_count):
            name, block = self.blocks[index]
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
            "forest_hyperedge_count": self.forest_hyperedge_count,
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
        values = list(discovered)
    else:
        if isinstance(requested, (str, bytes, Mapping)) or not isinstance(
            requested, Sequence
        ):
            raise ValueError("signatures must be a bounded sequence")
        requested_count = len(requested)
        if requested_count > MAX_COMPILED_RELATIONS:
            raise ValueError(
                f"signatures exceed bounded limit {MAX_COMPILED_RELATIONS}"
            )
        values = [requested[index] for index in range(requested_count)]
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
    values.sort(
        key=lambda item: (
            item.source_plane,
            item.relation,
            item.target_plane,
        )
    )
    return tuple(values)


def _require_complete_endpoint_planes(
    snapshot: FourfoldSnapshot,
    signatures: Sequence[RelationSignature],
) -> None:
    planes = snapshot.planes
    incomplete = sorted(
        {
            plane
            for signature in signatures
            for plane in (signature.source_plane, signature.target_plane)
            if planes[FOURFOLD_PLANES.index(plane)].status != "complete"
        }
    )
    if incomplete:
        detail = ", ".join(
            f"{plane}={planes[FOURFOLD_PLANES.index(plane)].status}"
            for plane in incomplete
        )
        raise ValueError(
            "relation compilation requires complete endpoint planes; " + detail
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
        dict[tuple[int, int], Any],
    ],
    *,
    signature: RelationSignature,
    source_index: int,
    target_index: int,
    scalar_value: bool | int | None,
    evidence_atoms: Sequence[str] | None,
) -> None:
    bucket = facts.get(signature)
    if bucket is None:
        bucket = {}
        facts[signature] = bucket
    coordinate = (source_index, target_index)
    if coordinate not in bucket and len(bucket) >= MAX_BLOCK_ENTRIES:
        raise ValueError(
            f"relation {relation_block_name(signature)!r} exceeds "
            f"bounded entry limit {MAX_BLOCK_ENTRIES}"
        )
    if evidence_atoms is None:
        bucket.setdefault(coordinate, scalar_value)
        return
    evidence_bundles = bucket.get(coordinate)
    if evidence_bundles is None:
        evidence_bundles = set()
        bucket[coordinate] = evidence_bundles
    atoms = tuple(sorted(set(evidence_atoms)))
    evidence_bundles.add(atoms)


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
    plans. When omitted, every representable binary relation signature retained
    by Fourfold or exposed by verified cross-plane bindings is compiled. Every
    selected relation requires ``complete`` Fourfold endpoint planes so sparse
    zeroes cannot silently encode unknown partial or absent facts. Same-plane
    Forest edges are authority inputs only when their exact canonical digest is
    retained by that plane's ``relation_sha256s``; unretained rows are omitted
    from the regenerable Tensor view rather than readmitted or treated as a
    second authority. Cross-plane Forest edges are admission checks only: an
    authoritative cross-plane row must come from an exact included verified
    Fourfold binding. Retained Forest hyperedges and undirected Forest edges are
    never flattened into pairwise/directional facts; discover-all and an
    explicitly selected conflicting relation fail closed instead.

    Same-plane Forest edges and verified bindings are deduplicated by semantic
    endpoint/relation identity. The compiler admits only an exact constitutional
    Forest/Fourfold node partition, then binds retained endpoints to their
    canonical Fourfold plane indices once and reuses the indexed block owner;
    explicit plans key their already-validated requested signatures once and
    reuse those same records during binding/edge admission instead of rebuilding
    an equivalent ``RelationSignature`` for every inspected record. The compiler
    does not readmit already-authoritative labels through a second coordinate
    validation pass. The evidence observer retains canonical provenance
    alternatives; scalar observers keep their final semiring scalars in the
    same bounded per-signature coordinate map and do not retain per-edge
    provenance in the admission-to-materialization staging records.
    """

    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    if type(include_verified_bindings) is not bool:
        raise ValueError("include_verified_bindings must be boolean")
    observer_name = _observer_name(semiring)
    retain_evidence = observer_name == "evidence-dag"
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

    _forest_node_partition(forest, snapshot)
    planes = snapshot.planes
    node_location: dict[str, tuple[str, int]] = {}
    for plane in planes:
        for position, node_id in enumerate(plane.node_ids):
            node_location[node_id] = (plane.plane, position)

    retained_relation_digests = {
        plane.plane: frozenset(plane.relation_sha256s)
        for plane in planes
    }

    requested_signatures = (
        None
        if signatures is None
        else _selected_signatures(signatures, set())
    )
    requested_by_key = (
        None
        if requested_signatures is None
        else {
            (
                signature.source_plane,
                signature.relation,
                signature.target_plane,
            ): signature
            for signature in requested_signatures
        }
    )
    if requested_signatures is not None:
        _require_complete_endpoint_planes(snapshot, requested_signatures)

    for hyperedge in forest.hyperedges:
        member_planes: set[str] = set()
        for member in hyperedge.members:
            location = node_location.get(member)
            if location is None:
                raise ValueError(
                    f"Forest hyperedge {hyperedge.id!r} references an endpoint "
                    "outside the Fourfold snapshot"
                )
            member_planes.add(location[0])
        if not member_planes:
            raise ValueError(
                f"Forest hyperedge {hyperedge.id!r} must retain at least one member"
            )
        conflicts = requested_signatures is None
        if requested_signatures is not None:
            conflicts = any(
                signature.relation == hyperedge.relation
                and (
                    (
                        signature.source_plane == signature.target_plane
                        and member_planes == {signature.source_plane}
                    )
                    or (
                        signature.source_plane != signature.target_plane
                        and signature.source_plane in member_planes
                        and signature.target_plane in member_planes
                    )
                )
                for signature in requested_signatures
            )
        if not conflicts:
            continue
        if len(member_planes) == 1:
            plane = next(iter(member_planes))
            hyperedge_digest = canonical_sha(hyperedge.to_dict())
            if hyperedge_digest not in retained_relation_digests[plane]:
                continue
        raise ValueError(
            f"cannot flatten a retained ForestHyperedge {hyperedge.id!r} "
            "into pairwise relation blocks without losing semantics"
        )

    discovered: set[RelationSignature] = set()
    binding_records: list[tuple[CrossPlaneBinding, RelationSignature, int, int]] = []
    included_binding_keys: set[tuple[str, str, str, str, str]] = set()
    verified_binding_count = len(snapshot.bindings) if include_verified_bindings else 0
    if include_verified_bindings:
        for binding in snapshot.bindings:
            signature_key = (
                binding.source_plane,
                binding.relation,
                binding.target_plane,
            )
            if requested_by_key is None:
                signature = RelationSignature(*signature_key)
            else:
                signature = requested_by_key.get(signature_key)
                if signature is None:
                    continue
            included_binding_keys.add(
                (
                    binding.source_plane,
                    binding.source_node_id,
                    binding.target_plane,
                    binding.target_node_id,
                    binding.relation,
                )
            )
            source_index = node_location[binding.source_node_id][1]
            target_index = node_location[binding.target_node_id][1]
            binding_records.append((binding, signature, source_index, target_index))
            if requested_by_key is None:
                discovered.add(signature)

    edge_records: list[
        tuple[RelationSignature, int, int, str | None, tuple[str, ...] | None]
    ] = []
    for edge in forest.edges:
        source_location = node_location.get(edge.source)
        target_location = node_location.get(edge.target)
        if source_location is None or target_location is None:
            raise ValueError(
                f"Forest edge {edge.relation!r} references an endpoint outside "
                "the Fourfold snapshot"
            )
        source_plane, source_index = source_location
        target_plane, target_index = target_location
        signature_key = (source_plane, edge.relation, target_plane)
        if requested_by_key is None:
            signature = RelationSignature(*signature_key)
        else:
            signature = requested_by_key.get(signature_key)
        edge_digest: str | None = None
        if source_plane == target_plane:
            if signature is None:
                continue
            retained_digests = retained_relation_digests[source_plane]
            if not retained_digests:
                continue
            edge_digest = canonical_sha(edge.to_dict())
            if edge_digest not in retained_digests:
                continue
        if not edge.directed:
            conflicts = requested_by_key is None or signature is not None
            if requested_by_key is not None and not conflicts:
                reverse_signature_key = (
                    target_plane,
                    edge.relation,
                    source_plane,
                )
                conflicts = reverse_signature_key in requested_by_key
            if conflicts:
                raise ValueError(
                    f"cannot flatten undirected ForestEdge {edge.relation!r} "
                    "into directed relation blocks without losing semantics"
                )
            continue
        if signature is None:
            continue
        if source_plane != target_plane:
            binding_key = (
                source_plane,
                edge.source,
                target_plane,
                edge.target,
                edge.relation,
            )
            if binding_key not in included_binding_keys:
                raise ValueError(
                    f"cross-plane ForestEdge {edge.relation!r} requires an exact "
                    "included verified Fourfold binding before relation compilation"
                )
            continue
        if edge_digest is None:
            raise AssertionError("same-plane edge admission lost its retained digest")
        edge_records.append(
            (
                signature,
                source_index,
                target_index,
                edge_digest if retain_evidence else None,
                edge.evidence if retain_evidence else None,
            )
        )
        if requested_by_key is None:
            discovered.add(signature)

    selected = (
        requested_signatures
        if requested_signatures is not None
        else _selected_signatures(None, discovered)
    )
    if requested_signatures is None:
        _require_complete_endpoint_planes(snapshot, selected)
    scalar_value: bool | int | None
    if observer_name == "boolean":
        scalar_value = True
    elif observer_name == "natural":
        scalar_value = 1
    else:
        scalar_value = None

    facts: dict[
        RelationSignature,
        dict[tuple[int, int], Any],
    ] = {}
    for (
        signature,
        source_index,
        target_index,
        edge_digest,
        edge_evidence,
    ) in edge_records:
        if retain_evidence:
            if edge_digest is None or edge_evidence is None:
                raise AssertionError("evidence observer lost retained edge provenance")
            atoms: tuple[str, ...] | None = (edge_digest, *edge_evidence)
        else:
            atoms = None
        _record_fact(
            facts,
            signature=signature,
            source_index=source_index,
            target_index=target_index,
            scalar_value=scalar_value,
            evidence_atoms=atoms,
        )

    for binding, signature, source_index, target_index in binding_records:
        _record_fact(
            facts,
            signature=signature,
            source_index=source_index,
            target_index=target_index,
            scalar_value=scalar_value,
            evidence_atoms=(
                (binding.digest, *binding.evidence_sha256s)
                if retain_evidence
                else None
            ),
        )

    subject = ProjectionSubject(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_fourfold_sha256=snapshot.digest,
    )
    axes = {
        plane: TypedAxis(
            name=f"{plane}-nodes",
            plane=plane,
            labels=planes[index].node_ids,
        )
        for index, plane in enumerate(FOURFOLD_PLANES)
    }

    compiled: list[tuple[str, TypedRelationBlock[T]]] = []
    semantic_fact_count = 0
    for signature in selected:
        entries = facts.get(signature)
        if entries is None:
            entries = {}
        if retain_evidence:
            for coordinate in entries:
                evidence_bundles = entries[coordinate]
                entries[coordinate] = EvidenceValue(tuple(sorted(evidence_bundles)))
        block = TypedRelationBlock._from_indexed(
            subject,
            signature,
            axes[signature.source_plane],
            axes[signature.target_plane],
            entries,
            semiring,
        )
        compiled.append((relation_block_name(signature), block))
        semantic_fact_count += block.entry_count

    return CompiledRelationBlocks(
        subject=subject,
        semiring_name=observer_name,
        source_forest_sha256=forest_digest,
        blocks=tuple(compiled),
        semantic_fact_count=semantic_fact_count,
        forest_edge_count=len(forest.edges),
        forest_hyperedge_count=len(forest.hyperedges),
        verified_binding_count=verified_binding_count,
    )


__all__ = [
    "MAX_COMPILED_RELATIONS",
    "CompiledRelationBlocks",
    "compile_relation_blocks",
    "relation_block_name",
]