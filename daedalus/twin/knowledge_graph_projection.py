"""Regenerable graph projection for external knowledge and correlations.

The projection is designed for query stores, visualization and later latent
representations. It is *not* the authoritative ``KnowledgeForest`` and cannot
be converted into verified Fourfold bindings by construction. Every node and
edge is content-addressed back to the exact corpus and correlation result.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar, Mapping, Sequence

from ..spine.envelope import canonical_sha
from .knowledge_correlation import (
    KnowledgeCorrelationError,
    KnowledgeCorrelationResult,
)
from .knowledge_sources import KnowledgeCorpus


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise KnowledgeCorrelationError(f"{name} must be lowercase sha256")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _freeze(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        frozen = tuple(_freeze(item) for item in value)
        if isinstance(value, (set, frozenset)):
            return tuple(sorted(frozen, key=repr))
        return frozen
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {key: _thaw(item) for key, item in value}
        return [_thaw(item) for item in value]
    return value


def _attribute_rows(values: Sequence[tuple[str, Any]]) -> tuple[tuple[str, Any], ...]:
    rows = tuple(sorted((str(key), _freeze(value)) for key, value in values))
    if len({key for key, _ in rows}) != len(rows):
        raise KnowledgeCorrelationError("overlay attributes must be unique")
    return rows


@dataclass(frozen=True)
class KnowledgeOverlayNode:
    node_id: str
    kind: str
    attributes: tuple[tuple[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise KnowledgeCorrelationError("overlay node_id must not be empty")
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise KnowledgeCorrelationError("overlay node kind must not be empty")
        object.__setattr__(self, "attributes", _attribute_rows(self.attributes))

    @property
    def attribute_map(self) -> Mapping[str, Any]:
        return dict(self.attributes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "attributes": [
                {"key": key, "value": _thaw(value)}
                for key, value in self.attributes
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeOverlayEdge:
    source_node_id: str
    target_node_id: str
    relation: str
    state: str
    evidence_sha256s: tuple[str, ...]
    attributes: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for name in ("source_node_id", "target_node_id", "relation", "state"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise KnowledgeCorrelationError(
                    f"overlay edge {name} must not be empty"
                )
        if self.state not in {
            "structural",
            "proposed",
            "source_supported",
            "diagnostic",
        }:
            raise KnowledgeCorrelationError("overlay edge state is invalid")
        evidence = tuple(
            sorted({_sha(value, "overlay edge evidence") for value in self.evidence_sha256s})
        )
        if self.state in {"source_supported", "diagnostic"} and not evidence:
            raise KnowledgeCorrelationError(
                "supported/diagnostic overlay edge requires evidence"
            )
        object.__setattr__(self, "evidence_sha256s", evidence)
        object.__setattr__(self, "attributes", _attribute_rows(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "relation": self.relation,
            "state": self.state,
            "evidence_sha256s": list(self.evidence_sha256s),
            "attributes": [
                {"key": key, "value": _thaw(value)}
                for key, value in self.attributes
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ExternalKnowledgeGraphProjection:
    snapshot_sha256: str
    corpus_sha256: str
    correlation_result_sha256: str
    nodes: tuple[KnowledgeOverlayNode, ...]
    edges: tuple[KnowledgeOverlayEdge, ...]

    SCHEMA: ClassVar[str] = "daedalus-external-knowledge-graph-projection/1"

    def __post_init__(self) -> None:
        for name in (
            "snapshot_sha256",
            "corpus_sha256",
            "correlation_result_sha256",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))
        nodes = tuple(sorted(self.nodes, key=lambda item: item.node_id))
        edges = tuple(
            sorted(
                self.edges,
                key=lambda item: (
                    item.source_node_id,
                    item.target_node_id,
                    item.relation,
                    item.state,
                    item.digest,
                ),
            )
        )
        if len({node.node_id for node in nodes}) != len(nodes):
            raise KnowledgeCorrelationError("overlay node ids must be unique")
        node_ids = {node.node_id for node in nodes}
        for edge in edges:
            if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                raise KnowledgeCorrelationError("overlay edge has a dangling endpoint")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)

    @property
    def node_map(self) -> Mapping[str, KnowledgeOverlayNode]:
        return {node.node_id: node for node in self.nodes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "snapshot_sha256": self.snapshot_sha256,
            "corpus_sha256": self.corpus_sha256,
            "correlation_result_sha256": self.correlation_result_sha256,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "authoritative": False,
            "verified_binding_output": False,
            "regenerable": True,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _node(node_id: str, kind: str, **attributes: Any) -> KnowledgeOverlayNode:
    return KnowledgeOverlayNode(
        node_id=node_id,
        kind=kind,
        attributes=tuple(sorted(attributes.items())),
    )


def _edge(
    source: str,
    target: str,
    relation: str,
    state: str,
    evidence: tuple[str, ...] = (),
    **attributes: Any,
) -> KnowledgeOverlayEdge:
    return KnowledgeOverlayEdge(
        source_node_id=source,
        target_node_id=target,
        relation=relation,
        state=state,
        evidence_sha256s=evidence,
        attributes=tuple(sorted(attributes.items())),
    )


def project_external_knowledge_graph(
    corpus: KnowledgeCorpus,
    result: KnowledgeCorrelationResult,
) -> ExternalKnowledgeGraphProjection:
    """Project exact source hierarchy and correlations into a safe graph."""

    if corpus.digest != result.corpus_sha256:
        raise KnowledgeCorrelationError(
            "correlation result does not bind the supplied corpus"
        )
    nodes: dict[str, KnowledgeOverlayNode] = {}
    edges: list[KnowledgeOverlayEdge] = []
    claim_nodes: dict[str, str] = {}

    for document in corpus.documents:
        source = document.source
        source_node_id = f"external-source:{source.digest}"
        document_node_id = f"external-document:{document.digest}"
        nodes[source_node_id] = _node(
            source_node_id,
            "external_knowledge_source",
            source_id=source.source_id,
            source_system=source.source_system,
            source_revision=source.source_revision,
            authority=source.authority,
            access_class=source.access_class,
            content_sha256=source.content_sha256,
        )
        nodes[document_node_id] = _node(
            document_node_id,
            "external_knowledge_document",
            document_id=document.document_id,
            title=document.title,
            document_key=document.document_key,
            authority=source.authority,
            access_class=source.access_class,
        )
        edges.append(
            _edge(
                source_node_id,
                document_node_id,
                "provides_revision",
                "structural",
            )
        )
        section_node_ids: dict[str, str] = {}
        for section in document.sections:
            section_node_id = f"external-section:{section.digest}"
            section_node_ids[section.section_id] = section_node_id
            nodes[section_node_id] = _node(
                section_node_id,
                "external_knowledge_section",
                section_id=section.section_id,
                heading_path=list(section.heading_path),
                line_start=section.line_start,
                line_end=section.line_end,
                text_sha256=canonical_sha(section.text),
            )
            edges.append(
                _edge(
                    document_node_id,
                    section_node_id,
                    "contains_section",
                    "structural",
                )
            )
        for claim in document.claims:
            claim_node_id = f"external-claim:{claim.digest}"
            claim_nodes[claim.digest] = claim_node_id
            nodes[claim_node_id] = _node(
                claim_node_id,
                "external_knowledge_claim",
                claim_id=claim.claim_id,
                text_sha256=canonical_sha(claim.text),
                line_start=claim.line_start,
                line_end=claim.line_end,
                authority=source.authority,
                access_class=source.access_class,
            )
            edges.append(
                _edge(
                    section_node_ids[claim.section_id],
                    claim_node_id,
                    "asserts_claim",
                    "structural",
                    (claim.source_sha256,),
                )
            )

    for card in result.cards:
        reference_id = f"fourfold-reference:{canonical_sha(card.node_id)}"
        nodes[reference_id] = _node(
            reference_id,
            "fourfold_node_reference",
            node_id=card.node_id,
            plane=card.plane,
            kind=card.kind,
            label=card.label,
            path=card.path,
            card_sha256=card.digest,
        )

    by_node_id = {
        node.attribute_map.get("node_id"): node.node_id
        for node in nodes.values()
        if node.kind == "fourfold_node_reference"
    }

    for bundle in result.bundles:
        claim_node_id = claim_nodes.get(bundle.claim.digest)
        if claim_node_id is None:
            raise KnowledgeCorrelationError(
                "correlation bundle claim is absent from corpus projection"
            )
        for proposal in bundle.proposals:
            target = by_node_id.get(proposal.target_node_id)
            if target is None:
                raise KnowledgeCorrelationError(
                    "correlation proposal target is absent from result cards"
                )
            edges.append(
                _edge(
                    claim_node_id,
                    target,
                    proposal.relation,
                    proposal.state,
                    proposal.evidence_sha256s,
                    score=proposal.score,
                    proposal_sha256=proposal.digest,
                    eligible_for_verification=proposal.eligible_for_verification,
                )
            )
        for contradiction in bundle.contradictions:
            diagnostic_id = f"external-contradiction:{contradiction.digest}"
            nodes[diagnostic_id] = _node(
                diagnostic_id,
                "knowledge_contradiction",
                contradiction_kind=contradiction.kind,
                detail=contradiction.detail,
                target_node_id=contradiction.target_node_id,
            )
            edges.append(
                _edge(
                    claim_node_id,
                    diagnostic_id,
                    "has_contradiction",
                    "diagnostic",
                    contradiction.evidence_sha256s,
                )
            )
        for unresolved in bundle.unresolved:
            unresolved_id = f"external-unresolved:{unresolved.digest}"
            nodes[unresolved_id] = _node(
                unresolved_id,
                "unresolved_knowledge_anchor",
                mention=unresolved.mention,
                reason=unresolved.reason,
            )
            edges.append(
                _edge(
                    claim_node_id,
                    unresolved_id,
                    "has_unresolved_anchor",
                    "structural",
                )
            )

    return ExternalKnowledgeGraphProjection(
        snapshot_sha256=result.snapshot_sha256,
        corpus_sha256=corpus.digest,
        correlation_result_sha256=result.digest,
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
    )


__all__ = [
    "ExternalKnowledgeGraphProjection",
    "KnowledgeOverlayEdge",
    "KnowledgeOverlayNode",
    "project_external_knowledge_graph",
]
