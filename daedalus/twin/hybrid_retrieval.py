"""BM25 seeding followed by exact typed Fourfold relation-plan execution.

BM25 and exact identifier lookup remain the fast physical seed index.
``ContractionPlan`` supplies the logical cross-plane query, while the canonical
CSR relation blocks execute it under Boolean, Natural and Evidence-DAG
observers. Results are proposals only; this module has no verifier, store,
scheduler, effect or promotion surface.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..schemas import _non_empty, _revision, _sha256
from ..spine.envelope import canonical_sha
from ..structcore.forest import KnowledgeForest
from .contracts import FOURFOLD_PLANES, FourfoldSnapshot
from .contractions import ContractionPlan, ReferenceContractionInterpreter
from .relation_blocks import RelationSignature, TypedRelationBlock
from .relation_compiler import CompiledRelationBlocks, compile_relation_blocks
from .semiring import (
    BooleanSemiring,
    EvidenceDagSemiring,
    EvidenceValue,
    NaturalSemiring,
)

MAX_HYBRID_DOCUMENTS = 100_000
MAX_DOCUMENT_BYTES = 262_144
MAX_QUERY_BYTES = 16_384
MAX_RESULTS = 4_096
MAX_RRF_K = 100_000

BM25_K1 = 1.5
BM25_B = 0.75
EXACT_IDENTIFIER_BOOST = 2.0

_ALNUM = re.compile(r"[A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _bounded_text(value: Any, name: str, limit: int) -> str:
    if type(value) is not str:
        raise ValueError(f"{name} must be text")
    try:
        raw = value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} contains an invalid Unicode surrogate") from exc
    if len(raw) > limit:
        raise ValueError(f"{name} exceeds {limit} UTF-8 bytes")
    return value


def _limit(value: Any, name: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_RESULTS:
        raise ValueError(f"{name} must be an integer from 1 to {MAX_RESULTS}")
    return value


def _tokens(text: str) -> tuple[str, ...]:
    text = _CAMEL.sub(" ", text.replace("_", " ").replace("-", " "))
    return tuple(
        token.lower()
        for token in _ALNUM.findall(text)
        if len(token) > 1
    )


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HybridDocument:
    """One lexical view of a node in an exact Fourfold revision."""

    node_id: str
    plane: str
    revision: str
    text: str
    source_locator: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _non_empty(self.node_id, "document.node_id", max_length=2_000)
        )
        if self.plane not in FOURFOLD_PLANES:
            raise ValueError(f"document.plane must be one of {FOURFOLD_PLANES}")
        object.__setattr__(
            self, "revision", _revision(self.revision, "document.revision")
        )
        object.__setattr__(
            self, "text", _bounded_text(self.text, "document.text", MAX_DOCUMENT_BYTES)
        )
        object.__setattr__(
            self,
            "source_locator",
            _bounded_text(self.source_locator, "document.source_locator", 8_192),
        )
        if not _tokens(self.search_text):
            raise ValueError("hybrid document has no token-bearing text")

    @property
    def search_text(self) -> str:
        return " ".join(
            part for part in (self.node_id, self.source_locator, self.text) if part
        )


def document_from_node_card(card: Mapping[str, Any]) -> HybridDocument:
    """Adapt the existing schema-light Node Card without importing experiments."""

    if not isinstance(card, Mapping):
        raise ValueError("node card must be an object")
    missing = {
        "node_id", "revision", "plane", "locator", "content"
    } - set(card)
    if missing:
        raise ValueError(f"node card is missing fields: {sorted(missing)}")
    locator, content = card["locator"], card["content"]
    if not isinstance(locator, Mapping) or not isinstance(content, Mapping):
        raise ValueError("node card locator and content must be objects")
    path = str(locator.get("path", ""))
    body = " ".join(
        str(content.get(key, ""))
        for key in ("name", "qualname", "signature", "doc", "text")
        if content.get(key)
    )
    return HybridDocument(
        node_id=str(card["node_id"]),
        plane=str(card["plane"]),
        revision=str(card["revision"]),
        text=body,
        source_locator=path,
    )


@dataclass(frozen=True)
class LexicalHit:
    node_id: str
    plane: str
    score: float
    rank: int
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "plane": self.plane,
            "score": self.score,
            "rank": self.rank,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class HybridHit:
    node_id: str
    plane: str
    score: float
    source_seed_rrf: float
    target_lexical_rrf: float
    graph_rrf: float
    supporting_seed_ids: tuple[str, ...]
    path_count: int
    evidence: EvidenceValue

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "plane": self.plane,
            "score": self.score,
            "channels": {
                "source_seed_rrf": self.source_seed_rrf,
                "target_lexical_rrf": self.target_lexical_rrf,
                "graph_rrf": self.graph_rrf,
            },
            "supporting_seed_ids": list(self.supporting_seed_ids),
            "path_count": self.path_count,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class HybridSearchResult:
    query_sha256: str
    source_plane: str
    target_plane: str
    plan_sha256: str
    projection_sha256s: tuple[str, ...]
    source_seeds: tuple[LexicalHit, ...]
    target_lexical: tuple[LexicalHit, ...]
    hits: tuple[HybridHit, ...]
    authority: str = "unverified-retrieval-proposal"
    automatic_promotions: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_sha256", _sha256(self.query_sha256, "query_sha256"))
        object.__setattr__(self, "plan_sha256", _sha256(self.plan_sha256, "plan_sha256"))
        if self.source_plane not in FOURFOLD_PLANES or self.target_plane not in FOURFOLD_PLANES:
            raise ValueError("hybrid result planes must be Fourfold planes")
        projections = tuple(
            _sha256(value, f"projection_sha256s[{index}]")
            for index, value in enumerate(self.projection_sha256s)
        )
        if len(projections) != 3:
            raise ValueError("hybrid result must bind three observer projections")
        object.__setattr__(self, "projection_sha256s", projections)
        if self.authority != "unverified-retrieval-proposal":
            raise ValueError("hybrid retrieval cannot mint authority")
        if self.automatic_promotions != 0:
            raise ValueError("hybrid retrieval cannot promote results")
        expected = tuple(sorted(self.hits, key=lambda hit: (-hit.score, hit.node_id)))
        if self.hits != expected:
            raise ValueError("hybrid hits must use canonical score ordering")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-fourfold-hybrid-retrieval/1",
            "authority": self.authority,
            "automatic_promotions": self.automatic_promotions,
            "query_sha256": self.query_sha256,
            "source_plane": self.source_plane,
            "target_plane": self.target_plane,
            "plan_sha256": self.plan_sha256,
            "projection_sha256s": list(self.projection_sha256s),
            "source_seeds": [hit.to_dict() for hit in self.source_seeds],
            "target_lexical": [hit.to_dict() for hit in self.target_lexical],
            "hits": [hit.to_dict() for hit in self.hits],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


class Bm25SeedIndex:
    """Small deterministic physical index over revision-bound node text."""

    def __init__(self, documents: Sequence[HybridDocument]) -> None:
        if isinstance(documents, (str, bytes, Mapping)):
            raise ValueError("documents must be a bounded sequence")
        if len(documents) > MAX_HYBRID_DOCUMENTS:
            raise ValueError(
                f"document count exceeds limit {MAX_HYBRID_DOCUMENTS}"
            )
        seen: set[str] = set()
        by_plane: dict[
            str,
            list[
                tuple[
                    HybridDocument,
                    tuple[str, ...],
                    Counter[str],
                    frozenset[str],
                ]
            ],
        ] = {
            plane: [] for plane in FOURFOLD_PLANES
        }
        for document in documents:
            if not isinstance(document, HybridDocument):
                raise ValueError("documents must contain HybridDocument records")
            if document.node_id in seen:
                raise ValueError(f"duplicate document node {document.node_id!r}")
            seen.add(document.node_id)
            tokens = _tokens(document.search_text)
            by_plane[document.plane].append(
                (
                    document,
                    tokens,
                    Counter(tokens),
                    frozenset(_tokens(document.node_id + " " + document.source_locator)),
                )
            )
        self._by_plane = {
            plane: tuple(sorted(rows, key=lambda row: row[0].node_id))
            for plane, rows in by_plane.items()
        }

    def rank(
        self, query: str, *, plane: str, limit: int = 20
    ) -> tuple[LexicalHit, ...]:
        query = _bounded_text(query, "query", MAX_QUERY_BYTES)
        if plane not in FOURFOLD_PLANES:
            raise ValueError(f"plane must be one of {FOURFOLD_PLANES}")
        limit = _limit(limit, "limit")
        terms = tuple(sorted(set(_tokens(query))))
        rows = self._by_plane[plane]
        if not terms or not rows:
            return ()

        df: Counter[str] = Counter()
        for _, _, counts, _ in rows:
            for term in terms:
                if term in counts:
                    df[term] += 1
        idf = {
            term: math.log(1.0 + (len(rows) - df[term] + 0.5) / (df[term] + 0.5))
            for term in terms
            if df[term]
        }
        average_length = sum(len(tokens) for _, tokens, _, _ in rows) / len(rows)
        scored: list[tuple[str, float, tuple[str, ...]]] = []
        for document, tokens, counts, exact_terms in rows:
            matched: set[str] = set()
            score = 0.0
            for term, weight in idf.items():
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                matched.add(term)
                denominator = frequency + BM25_K1 * (
                    1.0 - BM25_B + BM25_B * len(tokens) / average_length
                )
                score += weight * frequency * (BM25_K1 + 1.0) / denominator
            exact = set(terms).intersection(exact_terms)
            if exact:
                matched.update(exact)
                score += EXACT_IDENTIFIER_BOOST * len(exact)
            if score > 0.0:
                scored.append((document.node_id, score, tuple(sorted(matched))))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return tuple(
            LexicalHit(node_id, plane, score, rank, matched)
            for rank, (node_id, score, matched) in enumerate(scored[:limit], 1)
        )


class FourfoldHybridRetriever:
    """Use lexical seeds to restrict an exact cross-plane relation query."""

    def __init__(
        self,
        forest: KnowledgeForest,
        snapshot: FourfoldSnapshot,
        documents: Sequence[HybridDocument],
        *,
        signatures: Sequence[RelationSignature] | None = None,
    ) -> None:
        membership = {
            node_id: plane.plane
            for plane in snapshot.planes
            for node_id in plane.node_ids
        }
        documents = tuple(documents)
        for document in documents:
            if not isinstance(document, HybridDocument):
                raise ValueError("documents must contain HybridDocument records")
            if membership.get(document.node_id) != document.plane:
                raise ValueError(
                    f"document {document.node_id!r} is outside its declared plane"
                )
            if document.revision != snapshot.source_revision:
                raise ValueError(
                    f"document {document.node_id!r} binds another revision"
                )

        self._index = Bm25SeedIndex(documents)
        self._boolean = compile_relation_blocks(
            forest, snapshot, BooleanSemiring(), signatures=signatures
        )
        self._natural = compile_relation_blocks(
            forest, snapshot, NaturalSemiring(), signatures=signatures
        )
        self._evidence = compile_relation_blocks(
            forest, snapshot, EvidenceDagSemiring(), signatures=signatures
        )
        catalogs = {
            tuple(name for name, _ in projection.blocks)
            for projection in (self._boolean, self._natural, self._evidence)
        }
        if len(catalogs) != 1:
            raise ValueError("observer projections changed the relation catalog")

    @property
    def available_blocks(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self._boolean.blocks)

    @property
    def projection_receipts(
        self,
    ) -> tuple[
        CompiledRelationBlocks[bool],
        CompiledRelationBlocks[int],
        CompiledRelationBlocks[EvidenceValue],
    ]:
        return self._boolean, self._natural, self._evidence

    def lexical_search(
        self, query: str, *, plane: str, limit: int = 20
    ) -> tuple[LexicalHit, ...]:
        """Normal index fallback for exact or purely lexical questions."""

        return self._index.rank(query, plane=plane, limit=limit)

    @staticmethod
    def _evaluate(
        plan: ContractionPlan,
        projection: CompiledRelationBlocks[Any],
        semiring: Any,
    ) -> TypedRelationBlock[Any]:
        return ReferenceContractionInterpreter(semiring).evaluate(
            plan, projection.block_map
        )

    def search(
        self,
        query: str,
        plan: ContractionPlan,
        *,
        source_plane: str,
        target_plane: str,
        seed_limit: int = 20,
        result_limit: int = 20,
        rrf_k: int = 60,
    ) -> HybridSearchResult:
        query = _bounded_text(query, "query", MAX_QUERY_BYTES)
        if not isinstance(plan, ContractionPlan):
            raise ValueError("plan must be a ContractionPlan")
        if source_plane not in FOURFOLD_PLANES or target_plane not in FOURFOLD_PLANES:
            raise ValueError("source and target must be Fourfold planes")
        seed_limit, result_limit = (
            _limit(seed_limit, "seed_limit"),
            _limit(result_limit, "result_limit"),
        )
        if type(rrf_k) is not int or not 1 <= rrf_k <= MAX_RRF_K:
            raise ValueError(f"rrf_k must be an integer from 1 to {MAX_RRF_K}")

        source_seeds = self._index.rank(query, plane=source_plane, limit=seed_limit)
        target_lexical = self._index.rank(
            query, plane=target_plane, limit=result_limit
        )
        boolean = self._evaluate(plan, self._boolean, BooleanSemiring())
        natural = self._evaluate(plan, self._natural, NaturalSemiring())
        evidence = self._evaluate(plan, self._evidence, EvidenceDagSemiring())

        for result in (boolean, natural, evidence):
            if (
                result.signature.source_plane != source_plane
                or result.signature.target_plane != target_plane
            ):
                raise ValueError(
                    "plan output does not match the declared source/target planes"
                )
        if (
            natural.signature != boolean.signature
            or evidence.signature != boolean.signature
            or natural.row_axis != boolean.row_axis
            or evidence.row_axis != boolean.row_axis
            or natural.column_axis != boolean.column_axis
            or evidence.column_axis != boolean.column_axis
        ):
            raise ValueError("observer projections changed the typed result")

        boolean_map = {
            (source, target): value
            for source, target, value in boolean.iter_entries()
        }
        natural_map = {
            (source, target): value
            for source, target, value in natural.iter_entries()
        }
        evidence_map = {
            (source, target): value
            for source, target, value in evidence.iter_entries()
        }
        if set(boolean_map) != set(natural_map) or set(boolean_map) != set(evidence_map):
            raise ValueError("observer projections disagree on relation support")

        seed_by_id = {hit.node_id: hit for hit in source_seeds}
        target_rank = {hit.node_id: hit.rank for hit in target_lexical}
        support: dict[str, set[str]] = defaultdict(set)
        paths: dict[str, int] = defaultdict(int)
        proof: dict[str, EvidenceValue] = {}
        evidence_semiring = EvidenceDagSemiring()
        for source, target in sorted(boolean_map):
            if boolean_map[(source, target)] is not True or source not in seed_by_id:
                continue
            count = natural_map[(source, target)]
            value = evidence_map[(source, target)]
            if type(count) is not int or count <= 0:
                raise ValueError("natural observer returned an invalid path count")
            if not isinstance(value, EvidenceValue) or not value:
                raise ValueError("evidence observer returned empty path evidence")
            support[target].add(source)
            paths[target] += count
            proof[target] = evidence_semiring.add(
                proof.get(target, evidence_semiring.zero), value
            )

        graph_order = sorted(
            support,
            key=lambda node_id: (-paths[node_id], -len(support[node_id]), node_id),
        )
        graph_rank = {node_id: rank for rank, node_id in enumerate(graph_order, 1)}
        hits: list[HybridHit] = []
        for node_id in graph_order:
            source_rrf = math.fsum(
                1.0 / (rrf_k + seed_by_id[source].rank)
                for source in sorted(support[node_id])
            )
            target_rrf = (
                0.0
                if node_id not in target_rank
                else 1.0 / (rrf_k + target_rank[node_id])
            )
            graph_rrf = 1.0 / (rrf_k + graph_rank[node_id])
            hits.append(
                HybridHit(
                    node_id=node_id,
                    plane=target_plane,
                    score=source_rrf + target_rrf + graph_rrf,
                    source_seed_rrf=source_rrf,
                    target_lexical_rrf=target_rrf,
                    graph_rrf=graph_rrf,
                    supporting_seed_ids=tuple(sorted(support[node_id])),
                    path_count=paths[node_id],
                    evidence=proof[node_id],
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.node_id))
        return HybridSearchResult(
            query_sha256=_text_sha256(query),
            source_plane=source_plane,
            target_plane=target_plane,
            plan_sha256=plan.digest,
            projection_sha256s=(
                self._boolean.digest,
                self._natural.digest,
                self._evidence.digest,
            ),
            source_seeds=source_seeds,
            target_lexical=target_lexical,
            hits=tuple(hits[:result_limit]),
        )


__all__ = [
    "Bm25SeedIndex",
    "FourfoldHybridRetriever",
    "HybridDocument",
    "HybridHit",
    "HybridSearchResult",
    "LexicalHit",
    "document_from_node_card",
]
