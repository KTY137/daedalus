"""Strict wire parsers for knowledge dumps and correlation inputs.

The ingestion records deliberately use plain frozen dataclasses rather than a
second schema framework.  This module is their single fail-closed JSON boundary:
duplicate keys, unknown fields, missing fields, dangling graph endpoints and
non-finite weights are rejected before an imported artifact can participate in
correlation.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ..spine.envelope import canonical_json
from ..structcore.forest import (
    SCHEMA_VERSION as FOREST_SCHEMA,
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from ._reference_common import ReferenceCompileError, strict_json_loads
from .knowledge_sources import (
    KnowledgeClaim,
    KnowledgeCorpus,
    KnowledgeDocument,
    KnowledgeIngestError,
    KnowledgeSection,
    KnowledgeSource,
)


class KnowledgeWireError(ValueError):
    """Raised when a serialized knowledge/forest artifact is not canonical."""


def _object(
    value: Any,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise KnowledgeWireError(f"{label} must be an object")
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing or unknown:
        raise KnowledgeWireError(
            f"{label} has invalid fields (missing={missing}, unknown={unknown})"
        )
    return dict(value)


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KnowledgeWireError(f"{label} must be a sequence")
    return tuple(value)


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise KnowledgeWireError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise KnowledgeWireError(f"{label} must not be empty")
    if "\x00" in value:
        raise KnowledgeWireError(f"{label} contains a NUL byte")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise KnowledgeWireError(f"{label} must be an integer >= {minimum}")
    return value


def _number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KnowledgeWireError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise KnowledgeWireError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise KnowledgeWireError(f"{label} must be >= {minimum}")
    return result


def strict_json(value: str | bytes, label: str) -> Any:
    """Parse JSON with duplicate-key refusal and a knowledge-specific error."""

    try:
        return strict_json_loads(value, label)
    except ReferenceCompileError as exc:
        raise KnowledgeWireError(str(exc)) from exc


def _metadata(payload: Any) -> tuple[tuple[str, str], ...]:
    rows = _sequence(payload, "knowledge source metadata")
    result: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        item = _object(
            row,
            required=frozenset({"key", "value"}),
            label=f"knowledge source metadata[{index}]",
        )
        result.append(
            (
                _string(item["key"], f"metadata[{index}].key"),
                _string(item["value"], f"metadata[{index}].value", allow_empty=True),
            )
        )
    if len({key for key, _ in result}) != len(result):
        raise KnowledgeWireError("knowledge source metadata keys must be unique")
    return tuple(result)


def parse_knowledge_source(payload: Any) -> KnowledgeSource:
    body = _object(
        payload,
        required=frozenset(
            {
                "schema",
                "source_system",
                "source_instance",
                "source_item_key",
                "source_revision",
                "authority",
                "access_class",
                "imported_at",
                "content_sha256",
                "raw_artifact_locator",
                "metadata",
            }
        ),
        label="knowledge source",
    )
    if body["schema"] != KnowledgeSource.SCHEMA:
        raise KnowledgeWireError(
            f"knowledge source schema must be {KnowledgeSource.SCHEMA!r}"
        )
    try:
        return KnowledgeSource(
            source_system=body["source_system"],
            source_instance=body["source_instance"],
            source_item_key=body["source_item_key"],
            source_revision=body["source_revision"],
            authority=body["authority"],
            access_class=body["access_class"],
            imported_at=body["imported_at"],
            content_sha256=body["content_sha256"],
            raw_artifact_locator=body["raw_artifact_locator"],
            metadata=_metadata(body["metadata"]),
        )
    except KnowledgeIngestError as exc:
        raise KnowledgeWireError(str(exc)) from exc


def parse_knowledge_section(payload: Any) -> KnowledgeSection:
    body = _object(
        payload,
        required=frozenset(
            {
                "section_id",
                "heading_path",
                "ordinal",
                "line_start",
                "line_end",
                "text",
                "links",
            }
        ),
        label="knowledge section",
    )
    try:
        return KnowledgeSection(
            section_id=body["section_id"],
            heading_path=tuple(
                _string(value, "section heading")
                for value in _sequence(body["heading_path"], "heading_path")
            ),
            ordinal=_integer(body["ordinal"], "section.ordinal"),
            line_start=_integer(body["line_start"], "section.line_start", minimum=1),
            line_end=_integer(body["line_end"], "section.line_end", minimum=1),
            text=body["text"],
            links=tuple(
                _string(value, "section link")
                for value in _sequence(body["links"], "section.links")
            ),
        )
    except KnowledgeIngestError as exc:
        raise KnowledgeWireError(str(exc)) from exc


def parse_knowledge_claim(payload: Any) -> KnowledgeClaim:
    body = _object(
        payload,
        required=frozenset(
            {
                "claim_id",
                "document_id",
                "section_id",
                "ordinal",
                "line_start",
                "line_end",
                "text",
                "identifiers",
                "links",
                "source_sha256",
            }
        ),
        label="knowledge claim",
    )
    try:
        return KnowledgeClaim(
            claim_id=body["claim_id"],
            document_id=body["document_id"],
            section_id=body["section_id"],
            ordinal=_integer(body["ordinal"], "claim.ordinal"),
            line_start=_integer(body["line_start"], "claim.line_start", minimum=1),
            line_end=_integer(body["line_end"], "claim.line_end", minimum=1),
            text=body["text"],
            identifiers=tuple(
                _string(value, "claim identifier")
                for value in _sequence(body["identifiers"], "claim.identifiers")
            ),
            links=tuple(
                _string(value, "claim link")
                for value in _sequence(body["links"], "claim.links")
            ),
            source_sha256=body["source_sha256"],
        )
    except KnowledgeIngestError as exc:
        raise KnowledgeWireError(str(exc)) from exc


def parse_knowledge_document(payload: Any) -> KnowledgeDocument:
    body = _object(
        payload,
        required=frozenset(
            {
                "schema",
                "document_id",
                "source",
                "title",
                "document_key",
                "aliases",
                "sections",
                "claims",
            }
        ),
        label="knowledge document",
    )
    if body["schema"] != KnowledgeDocument.SCHEMA:
        raise KnowledgeWireError(
            f"knowledge document schema must be {KnowledgeDocument.SCHEMA!r}"
        )
    try:
        return KnowledgeDocument(
            document_id=body["document_id"],
            source=parse_knowledge_source(body["source"]),
            title=body["title"],
            document_key=body["document_key"],
            aliases=tuple(
                _string(value, "document alias")
                for value in _sequence(body["aliases"], "document.aliases")
            ),
            sections=tuple(
                parse_knowledge_section(value)
                for value in _sequence(body["sections"], "document.sections")
            ),
            claims=tuple(
                parse_knowledge_claim(value)
                for value in _sequence(body["claims"], "document.claims")
            ),
        )
    except KnowledgeIngestError as exc:
        raise KnowledgeWireError(str(exc)) from exc


def parse_knowledge_corpus(payload: Any) -> KnowledgeCorpus:
    body = _object(
        payload,
        required=frozenset({"schema", "corpus_id", "documents"}),
        label="knowledge corpus",
    )
    if body["schema"] != KnowledgeCorpus.SCHEMA:
        raise KnowledgeWireError(
            f"knowledge corpus schema must be {KnowledgeCorpus.SCHEMA!r}"
        )
    try:
        return KnowledgeCorpus(
            corpus_id=body["corpus_id"],
            documents=tuple(
                parse_knowledge_document(value)
                for value in _sequence(body["documents"], "corpus.documents")
            ),
        )
    except KnowledgeIngestError as exc:
        raise KnowledgeWireError(str(exc)) from exc


def parse_knowledge_corpus_json(value: str | bytes, label: str = "knowledge corpus") -> KnowledgeCorpus:
    return parse_knowledge_corpus(strict_json(value, label))


def knowledge_corpus_json(corpus: KnowledgeCorpus) -> str:
    if not isinstance(corpus, KnowledgeCorpus):
        raise KnowledgeWireError("corpus must be KnowledgeCorpus")
    return canonical_json(corpus.to_dict())


def _attributes(payload: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise KnowledgeWireError(f"{label} must be an object")
    for key in payload:
        if not isinstance(key, str):
            raise KnowledgeWireError(f"{label} contains a non-string key")
    return dict(payload)


def parse_knowledge_forest(payload: Any) -> KnowledgeForest:
    body = _object(
        payload,
        required=frozenset(
            {"schema", "root", "nodes", "edges", "hyperedges", "provenance"}
        ),
        label="knowledge forest",
    )
    if body["schema"] != FOREST_SCHEMA:
        raise KnowledgeWireError(f"forest schema must be {FOREST_SCHEMA!r}")

    nodes: list[ForestNode] = []
    for index, raw in enumerate(_sequence(body["nodes"], "forest.nodes")):
        item = _object(
            raw,
            required=frozenset({"id", "kind", "attributes"}),
            label=f"forest node[{index}]",
        )
        nodes.append(
            ForestNode(
                id=_string(item["id"], f"forest node[{index}].id"),
                kind=_string(item["kind"], f"forest node[{index}].kind"),
                attributes=_attributes(
                    item["attributes"], f"forest node[{index}].attributes"
                ),
            )
        )
    node_ids = {node.id for node in nodes}
    if len(node_ids) != len(nodes):
        raise KnowledgeWireError("forest node ids must be unique")

    edges: list[ForestEdge] = []
    for index, raw in enumerate(_sequence(body["edges"], "forest.edges")):
        item = _object(
            raw,
            required=frozenset(
                {
                    "source",
                    "target",
                    "relation",
                    "directed",
                    "weight",
                    "evidence",
                    "attributes",
                }
            ),
            label=f"forest edge[{index}]",
        )
        source = _string(item["source"], f"forest edge[{index}].source")
        target = _string(item["target"], f"forest edge[{index}].target")
        if source not in node_ids or target not in node_ids:
            raise KnowledgeWireError(f"forest edge[{index}] has a dangling endpoint")
        if not isinstance(item["directed"], bool):
            raise KnowledgeWireError(f"forest edge[{index}].directed must be boolean")
        edges.append(
            ForestEdge(
                source=source,
                target=target,
                relation=_string(item["relation"], f"forest edge[{index}].relation"),
                directed=item["directed"],
                weight=_number(item["weight"], f"forest edge[{index}].weight", minimum=0.0),
                evidence=tuple(
                    _string(value, f"forest edge[{index}] evidence")
                    for value in _sequence(item["evidence"], f"forest edge[{index}].evidence")
                ),
                attributes=_attributes(
                    item["attributes"], f"forest edge[{index}].attributes"
                ),
            )
        )

    hyperedges: list[ForestHyperedge] = []
    hyperedge_ids: set[str] = set()
    for index, raw in enumerate(_sequence(body["hyperedges"], "forest.hyperedges")):
        item = _object(
            raw,
            required=frozenset(
                {"id", "relation", "members", "weight", "evidence", "attributes"}
            ),
            label=f"forest hyperedge[{index}]",
        )
        edge_id = _string(item["id"], f"forest hyperedge[{index}].id")
        if edge_id in hyperedge_ids:
            raise KnowledgeWireError("forest hyperedge ids must be unique")
        hyperedge_ids.add(edge_id)
        members = tuple(
            _string(value, f"forest hyperedge[{index}] member")
            for value in _sequence(item["members"], f"forest hyperedge[{index}].members")
        )
        if len(members) < 2 or len(set(members)) != len(members):
            raise KnowledgeWireError(
                f"forest hyperedge[{index}] needs at least two unique members"
            )
        if not set(members).issubset(node_ids):
            raise KnowledgeWireError(f"forest hyperedge[{index}] has a dangling member")
        hyperedges.append(
            ForestHyperedge(
                id=edge_id,
                relation=_string(
                    item["relation"], f"forest hyperedge[{index}].relation"
                ),
                members=members,
                weight=_number(
                    item["weight"], f"forest hyperedge[{index}].weight", minimum=0.0
                ),
                evidence=tuple(
                    _string(value, f"forest hyperedge[{index}] evidence")
                    for value in _sequence(
                        item["evidence"], f"forest hyperedge[{index}].evidence"
                    )
                ),
                attributes=_attributes(
                    item["attributes"], f"forest hyperedge[{index}].attributes"
                ),
            )
        )

    return KnowledgeForest(
        root=_string(body["root"], "forest.root", allow_empty=True),
        nodes=tuple(nodes),
        edges=tuple(edges),
        hyperedges=tuple(hyperedges),
        provenance=_attributes(body["provenance"], "forest.provenance"),
        schema=FOREST_SCHEMA,
    )


def parse_knowledge_forest_json(value: str | bytes, label: str = "knowledge forest") -> KnowledgeForest:
    return parse_knowledge_forest(strict_json(value, label))


def knowledge_forest_json(forest: KnowledgeForest) -> str:
    if not isinstance(forest, KnowledgeForest):
        raise KnowledgeWireError("forest must be KnowledgeForest")
    return canonical_json(forest.to_dict())


__all__ = [
    "KnowledgeWireError",
    "knowledge_corpus_json",
    "knowledge_forest_json",
    "parse_knowledge_claim",
    "parse_knowledge_corpus",
    "parse_knowledge_corpus_json",
    "parse_knowledge_document",
    "parse_knowledge_forest",
    "parse_knowledge_forest_json",
    "parse_knowledge_section",
    "parse_knowledge_source",
    "strict_json",
]
