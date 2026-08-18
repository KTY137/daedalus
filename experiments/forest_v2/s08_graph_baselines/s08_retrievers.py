"""EXPERIMENT s08 — the two baselines this slice owes Gate 3, plus their controls.

Master plan §10 (Gate 3) names the required baselines; §13 turns two of them
into kill criteria.  This module implements exactly those two, honestly:

* **(a) code-only graph retrieval** — ``CodeGraphRetriever``.  BM25 over the
  code plane seeds a walk over the import/call neighbourhood; a module that no
  query token touches can still surface because it sits next to one that does.
  Its control is ``LexicalRetriever`` over the same code plane with the graph
  switched off, so any difference is the graph and nothing else.
* **(b) four separate single-plane indices without fusion** — two arms, because
  "no fusion" does not fix how the answer slots are shared.
  ``FourPlaneNoFusionRetriever`` splits ONE budget of k slots round-robin;
  ``UnionNoFusionRetriever`` gives each plane its own top-k and concatenates.
  Neither compares a score across planes — that is the invariant of the
  baseline — but the round-robin arm additionally starves whichever plane
  holds the answer, so only the pair of them says what no-fusion costs.
  ``SinglePlaneOracleRetriever`` reports the unreachable upper bound of that
  design (it is handed the gold label — it is a measuring stick, not a system).

Controls kept for the graph claim: ``rewire=True`` gives a degree-preserving
randomised graph (plan §13, "degree-preserving randomized cross-plane edges
perform equivalently"), so a graph gain that survives rewiring is not a gain.

Pure stdlib.  Nothing here writes, spawns, or reaches the network.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from s08_api import PLANES, Document, Hit, idf
from s08_corpus import Corpus, tokenize

# Frozen a priori, before any evaluation run.  Not swept for a headline number;
# the sensitivity table in the self-test is explicitly labelled post-hoc.
BM25_K1 = 1.2
BM25_B = 0.75
GRAPH_ALPHA = 0.5  # per-hop decay
GRAPH_HOPS = 2
GRAPH_SEEDS = 25


class Bm25Index:
    """Textbook BM25 over pre-tokenised documents.  No stemming, no tuning."""

    def __init__(self, docs: Sequence[Document], k1: float = BM25_K1, b: float = BM25_B) -> None:
        self.docs = list(docs)
        self.k1 = k1
        self.b = b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_len: list[int] = []
        for i, doc in enumerate(self.docs):
            counts: dict[str, int] = defaultdict(int)
            for token in doc.tokens:
                counts[token] += 1
            for term, tf in counts.items():
                self.postings[term].append((i, tf))
            self.doc_len.append(len(doc.tokens))
        n = len(self.docs)
        self.avgdl = (sum(self.doc_len) / n) if n else 0.0
        self.idf = {term: idf(n, len(post)) for term, post in self.postings.items()}

    def score_all(self, query_tokens: Iterable[str]) -> dict[int, float]:
        scores: dict[int, float] = defaultdict(float)
        for term in query_tokens:
            posting = self.postings.get(term)
            if not posting:
                continue
            weight = self.idf[term]
            for i, tf in posting:
                norm = 1.0 - self.b + self.b * (self.doc_len[i] / self.avgdl if self.avgdl else 0.0)
                scores[i] += weight * (tf * (self.k1 + 1.0)) / (tf + self.k1 * norm)
        return scores

    def search(self, text: str, k: int = 10) -> list[tuple[Document, float]]:
        scores = self.score_all(tokenize(text))
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], self.docs[kv[0]].doc_id))
        return [(self.docs[i], s) for i, s in ranked[:k]]


@dataclass
class LexicalRetriever:
    """One BM25 index over one document set.  The graph-off control."""

    name: str
    index: Bm25Index

    @classmethod
    def over(cls, name: str, docs: Sequence[Document]) -> "LexicalRetriever":
        return cls(name=name, index=Bm25Index(docs))

    def query(self, text: str, k: int = 10) -> list[Hit]:
        return [
            Hit(doc_id=d.doc_id, score=s, plane=d.plane, locator=d.locator, why="bm25")
            for d, s in self.index.search(text, k)
        ]


class CodeGraphRetriever:
    """(a) Code-only graph retrieval: lexical seeds, import/call neighbourhood ranking.

    score(d) = bm25_norm(d) + Σ_hops alpha^hop · (seed mass reaching d over
    weighted, degree-normalised edges).  Only the code plane exists here — the
    name is a promise: no type, data, or knowledge evidence enters.
    """

    def __init__(
        self,
        corpus: Corpus,
        alpha: float = GRAPH_ALPHA,
        hops: int = GRAPH_HOPS,
        seeds: int = GRAPH_SEEDS,
        rewire: bool = False,
        rewire_seed: int = 20260818,
        name: str | None = None,
    ) -> None:
        self.corpus = corpus
        self.alpha = alpha
        self.hops = hops
        self.seeds = seeds
        self.rewired = rewire
        self.index = Bm25Index(corpus.by_plane.get("code", []))
        self.module_of_doc = {doc_id: mod for mod, doc_id in corpus.doc_id_by_module.items()}
        self.adjacency = (
            _degree_preserving_rewire(corpus, rewire_seed) if rewire else corpus.adjacency()
        )
        self.degree = {m: sum(w for _, w in nbrs) for m, nbrs in self.adjacency.items()}
        self.name = name or (
            f"graph_code_only(alpha={alpha},hops={hops}{',rewired' if rewire else ''})"
        )

    def query(self, text: str, k: int = 10) -> list[Hit]:
        seeded = self.index.search(text, self.seeds)
        if not seeded:
            return []
        top = seeded[0][1] or 1.0
        scores: dict[str, float] = {}
        why: dict[str, str] = {}
        frontier: dict[str, float] = {}
        for doc, raw in seeded:
            mod = self.corpus.modules.get(self.module_of_doc.get(doc.doc_id, ""))
            norm = raw / top
            scores[doc.doc_id] = scores.get(doc.doc_id, 0.0) + norm
            why.setdefault(doc.doc_id, "bm25 seed")
            if mod is not None:
                frontier[mod.module] = frontier.get(mod.module, 0.0) + norm

        for hop in range(1, self.hops + 1):
            nxt: dict[str, float] = defaultdict(float)
            for module, mass in frontier.items():
                deg = self.degree.get(module, 0.0)
                if deg <= 0.0:
                    continue
                for neighbour, weight in self.adjacency.get(module, ()):
                    share = mass * (weight / deg) * (self.alpha**hop)
                    if share <= 1e-9:
                        continue
                    nxt[neighbour] += share
            for module, mass in nxt.items():
                doc_id = self.corpus.doc_id_by_module.get(module)
                if doc_id is None:
                    continue
                scores[doc_id] = scores.get(doc_id, 0.0) + mass
                why.setdefault(doc_id, f"graph {hop}-hop")
            frontier = dict(nxt)

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        out: list[Hit] = []
        for doc_id, score in ranked:
            doc = self.corpus.docs[doc_id]
            out.append(
                Hit(doc_id=doc_id, score=score, plane=doc.plane, locator=doc.locator, why=why.get(doc_id, ""))
            )
        return out


class FourPlaneNoFusionRetriever:
    """(b) Four independent single-plane indices, combined only by round-robin.

    There is no cross-plane scoring here and there must not be: four BM25
    scales are not commensurable, so any "just sort them together" merge would
    silently invent the fusion this baseline exists to *lack*.
    """

    def __init__(self, corpus: Corpus, order: Sequence[str] = PLANES, name: str = "four_plane_no_fusion") -> None:
        self.name = name
        self.order = tuple(order)
        self.indices = {plane: Bm25Index(corpus.by_plane.get(plane, [])) for plane in self.order}

    def query_plane(self, plane: str, text: str, k: int = 10) -> list[Hit]:
        return [
            Hit(doc_id=d.doc_id, score=s, plane=d.plane, locator=d.locator, why=f"bm25[{plane}]")
            for d, s in self.indices[plane].search(text, k)
        ]

    def query(self, text: str, k: int = 10) -> list[Hit]:
        per_plane = {plane: self.query_plane(plane, text, k) for plane in self.order}
        out: list[Hit] = []
        depth = 0
        while len(out) < k and any(len(hits) > depth for hits in per_plane.values()):
            for plane in self.order:
                hits = per_plane[plane]
                if depth < len(hits):
                    out.append(hits[depth])
                    if len(out) == k:
                        break
            depth += 1
        return out


class UnionNoFusionRetriever:
    """(b') The un-starved no-fusion arm: per-plane top-k, concatenated.

    ``FourPlaneNoFusionRetriever`` splits ONE budget of k slots across four
    planes round-robin.  Because every gold label in the frozen query set is a
    code document, only the code index can hold the answer, and round-robin
    hands it slots 1, 5, 9 — i.e. its top-3.  That arm therefore measures a
    *slot allocation*, not the absence of fusion, and reporting it as the
    no-fusion baseline understates no-fusion and flatters any cross-plane
    method.  This arm removes that confound: each plane answers with its own
    top-k, the lists are laid end to end, and **no score from one plane is
    ever compared with a score from another**.

    Two honest costs, stated rather than argued away:

    * **Budget.** It returns up to ``4k`` documents to answer a cutoff-``k``
      question.  R@k is unaffected (positions beyond k cannot count), but MRR
      over the full list is generous to this arm; ``truncated`` gives the
      apples-to-apples clip.
    * **Order.** Concatenation order is not a score comparison, but it does
      decide rank.  A fixed order is a *declared prior* over planes, and with a
      code-only gold set the code-first order is exactly the favourable one.
      ``order`` is therefore a constructor argument and the order sensitivity
      is measured, not assumed.
    """

    def __init__(
        self,
        corpus: Corpus,
        order: Sequence[str] = PLANES,
        name: str | None = None,
        truncate: bool = False,
    ) -> None:
        self.order = tuple(order)
        self.truncate = truncate
        self.indices = {plane: Bm25Index(corpus.by_plane.get(plane, [])) for plane in self.order}
        self.name = name or (
            f"union_no_fusion({'-'.join(self.order)}{',truncated' if truncate else ''})"
        )

    def query(self, text: str, k: int = 10) -> list[Hit]:
        out: list[Hit] = []
        for plane in self.order:
            for doc, score in self.indices[plane].search(text, k):
                out.append(
                    Hit(doc_id=doc.doc_id, score=score, plane=doc.plane, locator=doc.locator, why=f"bm25[{plane}]")
                )
        return out[:k] if self.truncate else out


class SinglePlaneOracleRetriever:
    """Upper bound only: an oracle picks the plane that ranks the gold best.

    It reads the gold label, so it is NOT a retrieval system and must never be
    reported as one.  It exists to say how much of the no-fusion baseline's
    loss is plane routing rather than ranking.
    """

    def __init__(self, base: FourPlaneNoFusionRetriever, name: str = "oracle_plane_routing") -> None:
        self.base = base
        self.name = name
        self._gold: str | None = None

    def set_gold(self, gold_doc_id: str) -> None:
        self._gold = gold_doc_id

    def query(self, text: str, k: int = 10) -> list[Hit]:
        best: list[Hit] = []
        best_rank = None
        for plane in self.base.order:
            hits = self.base.query_plane(plane, text, k)
            rank = next((i for i, h in enumerate(hits, 1) if h.doc_id == self._gold), None)
            if rank is not None and (best_rank is None or rank < best_rank):
                best_rank, best = rank, hits
        return best or self.base.query_plane(self.base.order[0], text, k)


def _degree_preserving_rewire(corpus: Corpus, seed: int) -> dict[str, list[tuple[str, float]]]:
    """Randomise the graph while keeping each module's edge COUNT.

    Repeated double-edge swaps on the undirected edge list; the weight travels
    with the edge, so unweighted degree is exactly preserved while summed edge
    weight per node may shift — stated here rather than claimed away.  A graph
    "gain" that survives this control is a degree artefact, not structure
    (plan §13).
    """
    rng = random.Random(seed)
    edges = [(a, b, w) for (a, b), w in corpus.edges.items()]
    present = {(a, b) for a, b, _ in edges}
    for _ in range(10 * len(edges)):
        if len(edges) < 2:
            break
        i, j = rng.randrange(len(edges)), rng.randrange(len(edges))
        if i == j:
            continue
        a1, b1, w1 = edges[i]
        a2, b2, w2 = edges[j]
        if len({a1, b1, a2, b2}) < 4:
            continue
        n1 = (a1, b2) if a1 < b2 else (b2, a1)
        n2 = (a2, b1) if a2 < b1 else (b1, a2)
        if n1 in present or n2 in present:
            continue
        present.discard((a1, b1) if a1 < b1 else (b1, a1))
        present.discard((a2, b2) if a2 < b2 else (b2, a2))
        present.add(n1)
        present.add(n2)
        edges[i] = (n1[0], n1[1], w1)
        edges[j] = (n2[0], n2[1], w2)
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for a, b, w in edges:
        adj[a].append((b, w))
        adj[b].append((a, w))
    return dict(adj)
