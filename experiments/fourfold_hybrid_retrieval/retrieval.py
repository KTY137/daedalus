"""Hybrid retrieval: lexical indices propose seeds, typed relations expand them.

This module deliberately does not replace BM25.  It uses the frozen s07 BM25
implementation as a physical seed/direct-candidate index, then executes a
logical Fourfold contraction plan over deterministic relation blocks and fuses
both rankings with reciprocal-rank fusion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from daedalus.spine.envelope import canonical_sha
from experiments.forest_v2.s07_bm25.bm25_index import (
    BM25Index,
    IndexConfig,
    tokenize,
)

from .planner import (
    ContractionPlan,
    PhysicalPlanner,
    ReferenceContractionExecutor,
)
from .relations import ProjectionSubject, RelationBlockCatalog

MAX_NODE_DOCUMENTS = 250_000
MAX_SEED_HITS = 1_000
MAX_RESULT_HITS = 10_000


@dataclass(frozen=True)
class NodeDocument:
    node_id: str
    plane: str
    text: str
    locator: str = ""

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("node_id", self.node_id, 2_000),
            ("plane", self.plane, 32),
            ("text", self.text, 262_144),
            ("locator", self.locator, 2_000),
        ):
            if type(value) is not str or len(value) > limit:
                raise ValueError(f"document.{name} must be text up to {limit} characters")
            if name != "locator" and not value:
                raise ValueError(f"document.{name} must not be empty")
            if "\x00" in value:
                raise ValueError(f"document.{name} contains a NUL byte")

    @property
    def index_text(self) -> str:
        # Identity fields remain separate in the receipt, but exact names are
        # valid retrieval evidence and therefore deliberately indexed.
        return " ".join(part for part in (self.node_id, self.locator, self.text) if part)


@dataclass(frozen=True)
class LexicalHit:
    rank: int
    node_id: str
    plane: str
    score: float
    exact_identity_matches: int
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "node_id": self.node_id,
            "plane": self.plane,
            "score": self.score,
            "exact_identity_matches": self.exact_identity_matches,
            "matched_terms": list(self.matched_terms),
        }


class NodeDocumentIndex:
    """One deterministic BM25 + exact-identity index over Node Cards."""

    def __init__(self, documents: Sequence[NodeDocument]) -> None:
        if isinstance(documents, (str, bytes, Mapping)) or not isinstance(
            documents, Sequence
        ):
            raise ValueError("documents must be a bounded sequence")
        if not 1 <= len(documents) <= MAX_NODE_DOCUMENTS:
            raise ValueError(
                f"documents must contain 1..{MAX_NODE_DOCUMENTS} NodeDocument records"
            )
        by_id: dict[str, NodeDocument] = {}
        identity_tokens: dict[str, frozenset[str]] = {}
        for index, document in enumerate(documents):
            if not isinstance(document, NodeDocument):
                raise ValueError(f"documents[{index}] must be NodeDocument")
            if document.node_id in by_id:
                raise ValueError("documents must not repeat a node_id")
            by_id[document.node_id] = document
            identity_tokens[document.node_id] = frozenset(
                tokenize(f"{document.node_id} {document.locator}")
            )
        self._documents = dict(sorted(by_id.items()))
        self._identity_tokens = identity_tokens
        self._bm25 = BM25Index.from_documents(
            {
                node_id: document.index_text
                for node_id, document in self._documents.items()
            },
            IndexConfig(path_weight=0),
        )

    @property
    def documents(self) -> Mapping[str, NodeDocument]:
        return dict(self._documents)

    @property
    def count(self) -> int:
        return len(self._documents)

    def search(
        self,
        query: str,
        *,
        allowed_planes: Iterable[str] | None = None,
        k: int = 20,
    ) -> tuple[LexicalHit, ...]:
        if type(query) is not str:
            raise ValueError("query must be text")
        if type(k) is not int or not 0 <= k <= MAX_RESULT_HITS:
            raise ValueError(f"k must be in [0, {MAX_RESULT_HITS}]")
        if k == 0:
            return ()
        plane_filter = None
        if allowed_planes is not None:
            if isinstance(allowed_planes, (str, bytes, Mapping)):
                raise ValueError("allowed_planes must be an iterable of plane names")
            plane_filter = frozenset(allowed_planes)

        query_tokens = frozenset(tokenize(query))
        raw_hits = self._bm25.search(query, k=self._bm25.num_documents)
        ranked: list[tuple[str, float, int, tuple[str, ...]]] = []
        for hit in raw_hits:
            document = self._documents[hit.path]
            if plane_filter is not None and document.plane not in plane_filter:
                continue
            exact_matches = len(
                query_tokens.intersection(self._identity_tokens[document.node_id])
            )
            ranked.append(
                (
                    document.node_id,
                    float(hit.score),
                    exact_matches,
                    hit.matched_terms,
                )
            )
        ranked.sort(key=lambda item: (-item[2], -item[1], item[0]))
        return tuple(
            LexicalHit(
                rank=rank,
                node_id=node_id,
                plane=self._documents[node_id].plane,
                score=score,
                exact_identity_matches=exact_matches,
                matched_terms=matched_terms,
            )
            for rank, (node_id, score, exact_matches, matched_terms) in enumerate(
                ranked[:k],
                start=1,
            )
        )


@dataclass(frozen=True)
class HybridRequest:
    query: str
    plan: ContractionPlan
    seed_top_k: int = 12
    result_limit: int = 20
    rrf_k: int = 60
    direct_weight: float = 1.0
    graph_weight: float = 1.0

    def __post_init__(self) -> None:
        if type(self.query) is not str or not self.query:
            raise ValueError("request.query must be non-empty text")
        if not isinstance(self.plan, ContractionPlan):
            raise ValueError("request.plan must be ContractionPlan")
        if type(self.seed_top_k) is not int or not 1 <= self.seed_top_k <= MAX_SEED_HITS:
            raise ValueError(f"seed_top_k must be in [1, {MAX_SEED_HITS}]")
        if type(self.result_limit) is not int or not 1 <= self.result_limit <= MAX_RESULT_HITS:
            raise ValueError(f"result_limit must be in [1, {MAX_RESULT_HITS}]")
        if type(self.rrf_k) is not int or not 1 <= self.rrf_k <= 10_000:
            raise ValueError("rrf_k must be in [1, 10000]")
        for name, value in (
            ("direct_weight", self.direct_weight),
            ("graph_weight", self.graph_weight),
        ):
            if isinstance(value, bool) or type(value) not in (int, float):
                raise ValueError(f"{name} must be a finite non-negative number")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.direct_weight == 0.0 and self.graph_weight == 0.0:
            raise ValueError("at least one retrieval contribution must be enabled")


@dataclass(frozen=True)
class HybridHit:
    rank: int
    node_id: str
    plane: str
    score: float
    direct_rrf: float
    graph_rrf: float
    direct_rank: int | None
    supporting_seed_ids: tuple[str, ...]
    branch_names: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    derivation_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "node_id": self.node_id,
            "plane": self.plane,
            "score": self.score,
            "direct_rrf": self.direct_rrf,
            "graph_rrf": self.graph_rrf,
            "direct_rank": self.direct_rank,
            "supporting_seed_ids": list(self.supporting_seed_ids),
            "branch_names": list(self.branch_names),
            "evidence_sha256s": list(self.evidence_sha256s),
            "derivation_count": self.derivation_count,
        }


@dataclass(frozen=True)
class HybridRetrievalReceipt:
    query: str
    subject: ProjectionSubject
    plan_digest: str
    catalog_digest: str
    lexical_seeds: tuple[LexicalHit, ...]
    direct_candidates: tuple[LexicalHit, ...]
    hits: tuple[HybridHit, ...]
    strategies: tuple[str, ...]
    authority: str = "unverified-retrieval-proposal"
    proposal_only: bool = True
    schema: str = "daedalus-fourfold-hybrid-retrieval/1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authority": self.authority,
            "proposal_only": self.proposal_only,
            "query": self.query,
            "subject": self.subject.to_dict(),
            "plan_digest": self.plan_digest,
            "catalog_digest": self.catalog_digest,
            "strategies": list(self.strategies),
            "lexical_seeds": [hit.to_dict() for hit in self.lexical_seeds],
            "direct_candidates": [hit.to_dict() for hit in self.direct_candidates],
            "hits": [hit.to_dict() for hit in self.hits],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass
class _Aggregate:
    direct_rrf: float = 0.0
    graph_rrf: float = 0.0
    direct_rank: int | None = None
    seeds: set[str] = field(default_factory=set)
    branches: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    derivation_count: int = 0


class HybridRetriever:
    """BM25/exact seeds -> typed graph expansion -> deterministic RRF."""

    def __init__(
        self,
        catalog: RelationBlockCatalog,
        documents: Sequence[NodeDocument],
        *,
        planner: PhysicalPlanner | None = None,
        executor: ReferenceContractionExecutor | None = None,
    ) -> None:
        if not isinstance(catalog, RelationBlockCatalog):
            raise ValueError("catalog must be RelationBlockCatalog")
        self.catalog = catalog
        self.index = NodeDocumentIndex(documents)
        for document in self.index.documents.values():
            catalog_plane = catalog.plane_of(document.node_id)
            if document.plane != catalog_plane:
                raise ValueError(
                    f"document plane for {document.node_id!r} differs from catalog"
                )
        self.planner = planner or PhysicalPlanner()
        self.executor = executor or ReferenceContractionExecutor()

    def search(self, request: HybridRequest) -> HybridRetrievalReceipt:
        if not isinstance(request, HybridRequest):
            raise ValueError("request must be HybridRequest")
        physical = self.planner.compile(request.plan, self.catalog)

        seeds = self.index.search(
            request.query,
            allowed_planes=(request.plan.start_plane,),
            k=request.seed_top_k,
        )
        direct = self.index.search(
            request.query,
            allowed_planes=(request.plan.end_plane,),
            k=min(self.index.count, MAX_RESULT_HITS),
        )

        aggregates: dict[str, _Aggregate] = {}
        direct_weight = float(request.direct_weight)
        graph_weight = float(request.graph_weight)

        for hit in direct:
            aggregate = aggregates.setdefault(hit.node_id, _Aggregate())
            aggregate.direct_rank = hit.rank
            aggregate.direct_rrf = direct_weight / (request.rrf_k + hit.rank)

        strategies = physical.strategies
        for seed in seeds:
            result = self.executor.execute(
                physical,
                self.catalog,
                seeds=(seed.node_id,),
            )
            for graph_rank, hit in enumerate(result.hits, start=1):
                aggregate = aggregates.setdefault(hit.node_id, _Aggregate())
                # Two-stage RRF: an early lexical seed and an early graph hit
                # contribute more.  No raw BM25/edge-weight scale is mixed.
                aggregate.graph_rrf += (
                    graph_weight
                    * hit.branch_coverage
                    / (request.rrf_k + seed.rank + graph_rank - 1)
                )
                aggregate.seeds.add(seed.node_id)
                aggregate.branches.update(hit.branch_names)
                aggregate.evidence.update(hit.evidence_sha256s)
                aggregate.derivation_count += hit.derivation_count

        ranked: list[tuple[str, _Aggregate]] = list(aggregates.items())
        ranked.sort(
            key=lambda item: (
                -(item[1].direct_rrf + item[1].graph_rrf),
                -item[1].graph_rrf,
                -len(item[1].evidence),
                -item[1].derivation_count,
                item[0],
            )
        )

        hits: list[HybridHit] = []
        node_planes = self.catalog.node_plane_map
        for rank, (node_id, aggregate) in enumerate(
            ranked[: request.result_limit],
            start=1,
        ):
            hits.append(
                HybridHit(
                    rank=rank,
                    node_id=node_id,
                    plane=node_planes[node_id],
                    score=aggregate.direct_rrf + aggregate.graph_rrf,
                    direct_rrf=aggregate.direct_rrf,
                    graph_rrf=aggregate.graph_rrf,
                    direct_rank=aggregate.direct_rank,
                    supporting_seed_ids=tuple(sorted(aggregate.seeds)),
                    branch_names=tuple(sorted(aggregate.branches)),
                    evidence_sha256s=tuple(sorted(aggregate.evidence)),
                    derivation_count=aggregate.derivation_count,
                )
            )

        return HybridRetrievalReceipt(
            query=request.query,
            subject=self.catalog.subject,
            plan_digest=request.plan.digest,
            catalog_digest=self.catalog.digest,
            lexical_seeds=seeds,
            direct_candidates=direct,
            hits=tuple(hits),
            strategies=strategies,
        )


__all__ = [
    "HybridHit",
    "HybridRequest",
    "HybridRetrievalReceipt",
    "HybridRetriever",
    "LexicalHit",
    "NodeDocument",
    "NodeDocumentIndex",
]
