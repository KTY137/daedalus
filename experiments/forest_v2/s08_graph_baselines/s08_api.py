"""EXPERIMENT s08 — the retrieval contract every baseline in this slice obeys.

This module is the *shared shape*, not a retriever: a plane-tagged document, a
scored hit that carries its own rationale, the ``Retriever`` protocol, and the
ranking metrics.  Slice s07 (lexical/BM25 retrieval) and slice s08 (graph and
single-plane baselines) are only comparable if they answer the same call:

    retriever.query(text: str, k: int) -> list[Hit]

Nothing here imports repository code.  Pure stdlib, read-only, no writes, no
network, no subprocess.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

PLANES: tuple[str, ...] = ("code", "type", "data", "knowledge")


@dataclass(frozen=True)
class Document:
    """One retrievable unit of exactly one Project-Twin plane.

    ``doc_id`` is the stable identity used by every index and by the gold
    labels: ``"<plane>:<locator>"``.  ``locator`` is a repo-relative POSIX
    path so a hit can always be pointed back at its source.
    """

    doc_id: str
    plane: str
    locator: str
    text: str
    symbols: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.plane not in PLANES:
            raise ValueError(f"unknown plane: {self.plane!r}")
        if self.doc_id != f"{self.plane}:{self.locator}":
            raise ValueError(f"doc_id must be '<plane>:<locator>': {self.doc_id!r}")


@dataclass(frozen=True)
class Hit:
    """A ranked answer.  ``why`` is provenance, not decoration.

    Scores are only comparable *within one retriever*.  Two independent
    single-plane indices produce incomparable scores by construction; that is
    the whole point of the no-fusion baseline and it must not be papered over
    by sorting four score lists together.
    """

    doc_id: str
    score: float
    plane: str
    locator: str
    why: str = ""


class Retriever(Protocol):
    """The one call s07 and s08 share."""

    name: str

    def query(self, text: str, k: int = 10) -> list[Hit]:  # pragma: no cover
        ...


@dataclass(frozen=True)
class Query:
    """One evaluation query with a single mechanically derived gold document."""

    qid: str
    family: str
    text: str
    gold_doc_id: str


@dataclass
class EvalResult:
    """RAW counts first, fractions second.  Fractions are derived, not stored truth."""

    retriever: str
    family: str
    n_queries: int
    hits_at: dict[int, int] = field(default_factory=dict)
    reciprocal_rank_sum: float = 0.0
    empty_results: int = 0
    seconds: float = 0.0

    def recall_at(self, k: int) -> float:
        return self.hits_at.get(k, 0) / self.n_queries if self.n_queries else 0.0

    @property
    def mrr(self) -> float:
        return self.reciprocal_rank_sum / self.n_queries if self.n_queries else 0.0

    def as_dict(self, ks: Sequence[int]) -> dict:
        return {
            "retriever": self.retriever,
            "family": self.family,
            "n_queries": self.n_queries,
            "hits_at": {str(k): self.hits_at.get(k, 0) for k in ks},
            "recall_at": {str(k): round(self.recall_at(k), 4) for k in ks},
            "mrr": round(self.mrr, 4),
            "empty_results": self.empty_results,
            "seconds": round(self.seconds, 3),
        }


def rank_of(hits: Sequence[Hit], gold_doc_id: str) -> int:
    """1-based rank of the gold document, or 0 when it is absent."""
    for i, hit in enumerate(hits, start=1):
        if hit.doc_id == gold_doc_id:
            return i
    return 0


def evaluate(
    retriever: Retriever,
    queries: Iterable[Query],
    ks: Sequence[int] = (1, 5, 10),
    family: str = "all",
) -> EvalResult:
    """Run every query once, count RAW hits at each cutoff, sum reciprocal ranks."""
    import time

    kmax = max(ks)
    result = EvalResult(retriever=retriever.name, family=family, n_queries=0)
    started = time.perf_counter()
    for query in queries:
        hits = retriever.query(query.text, k=kmax)
        result.n_queries += 1
        if not hits:
            result.empty_results += 1
        rank = rank_of(hits, query.gold_doc_id)
        if rank:
            result.reciprocal_rank_sum += 1.0 / rank
            for k in ks:
                if rank <= k:
                    result.hits_at[k] = result.hits_at.get(k, 0) + 1
    result.seconds = time.perf_counter() - started
    return result


def idf(n_docs: int, doc_freq: int) -> float:
    """Robertson/Sparck-Jones IDF as used by BM25 (always positive here)."""
    return math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
