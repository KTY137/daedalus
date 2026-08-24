"""The first genuine cross-plane score-fusion retriever in this program.

Every arm measured anywhere in ``forest_v2`` before this slice -- s07's
lexical index, s08's ``LexicalRetriever`` / ``CodeGraphRetriever`` /
``FourPlaneNoFusionRetriever`` / ``UnionNoFusionRetriever`` /
``SinglePlaneOracleRetriever``, s09's five baselines -- is either a single
index, a single-plane index, or a concatenation of per-plane results that
never compares one plane's score against another's.  The README's own s08
section names two things that are NOT fusion and says so in their class
names: ``FourPlaneNoFusionRetriever`` and ``UnionNoFusionRetriever``.  A
joint BM25 index over every plane's documents (``bm25_single_index_all_
planes`` in s08, ``bm25`` in s09) was very nearly mislabelled ``fusion``
once already -- ``s10_kill/test_s10_kill.py::test_no_arm_of_a_measured_run_
is_labelled_fusion`` exists specifically to catch that mistake happening
again.  A joint index shares one IDF space across every document regardless
of plane; it never computes a *per-plane* score to combine, so calling it
"fusion" is a category error, not merely an optimistic label.

This module is the thing those two kinds of non-fusion are not:

1. **Separate per-plane indices, for real.**  ``_partition`` splits the
   candidate universe into ``FUSION_PLANES`` (code, data, knowledge -- see
   below for why type and presentation are excluded), and ``_score_plane``
   runs an independent textbook BM25 pass over each bucket, with its own
   term frequencies, its own document-frequency table and its own IDF.  A
   term rare in the knowledge plane and common in the code plane gets two
   different IDF values in the two buckets -- exactly the thing a single
   joint index cannot do, because a joint index has only one IDF per term
   across the whole corpus.  ``test_fusion_retrievers.py`` exercises this
   directly: a fixture where a joint index and genuine per-plane scoring
   disagree, with the retriever asserted to produce the per-plane answer.
2. **Real per-plane rankings held in hand.**  ``FusionRetriever.rank``
   builds ``plane_scores: Dict[plane, List[Tuple[path, score]]]`` -- actual
   scored, ranked candidate lists, one per plane -- and stores the most
   recent set on ``self.last_plane_scores`` before any combination happens,
   so the claim "the retriever holds per-plane scores before combining
   them" is inspectable, not merely asserted in this docstring.
3. **Reciprocal Rank Fusion to combine them.**  ``_rrf_combine`` implements
   RRF(d) = sum over planes p containing d of ``1 / (k + rank_p(d))``,
   ``k=60`` -- the reported default from Cormack, Clarke & Buettcher,
   "Reciprocal Rank Fusion outperforms Condorcet and individual Rank
   Learning Methods", SIGIR 2009.  RRF combines RANKS rather than raw
   scores on purpose: s08's own retriever module says outright that "four
   BM25 scales are not commensurable", and RRF is the standard IR answer to
   that problem -- it never sums or compares a raw BM25 score from one
   plane against another's, only the *rank position* each plane's own,
   separately-computed scoring produced.  ``k=60`` is used unmodified, not
   swept for a favourable number; that is stated here so nobody has to take
   it on faith later.

What this retriever cannot reach, declared before any number is measured
(the schema.py rule this program already lives by: "an arm whose returned_
plane_counts name a plane outside its declared scope is rejected rather
than graded" -- so the declaration has to be true, not aspirational):

* **Type.**  No slice in this program has ever produced a file-level Type-
  plane artifact (s02, s08, s09-continuation-2 and ``s09_eval/to_s10.py``
  all record the identical gap independently).  There is nothing to index.
* **Presentation** (``.html``/``.css``).  Not a Project-Twin plane at all in
  ``s10_kill/schema.py`` (``PLANES = code/type/data/knowledge`` only), so it
  cannot be declared even if it were indexed.  It genuinely is not indexed
  here: folding it into ``code`` or ``knowledge`` to raise recall would
  misreport ``combines_planes`` and ``returned_plane_counts``, exactly the
  kind of fabrication this module exists to avoid.  A small, honestly-paid
  cost: 13 of 483 gold slots in the cross-plane corpus are ``.html``/``.css``
  and are structurally unreachable by every retriever in this module.

Pure stdlib.  No writes, no network, no subprocess, no model calls.  Reads
``experiments/forest_v2/s09_eval``'s own contract types and plane map
(consolidation, not a second implementation of either) -- nothing here
imports ``daedalus/``, and nothing in ``daedalus/`` imports this.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from experiments.forest_v2.s09_eval.contract import Candidate, QueryView
from experiments.forest_v2.s09_eval.taskset import plane_of
from experiments.forest_v2.s09_eval.tokens import TokenCache, word_tokens

#: Same k1/b as s09_eval.retrievers.Bm25 -- this module is not a different
#: scoring algorithm, only a narrower (per-plane) document scope, so any
#: difference between an arm here and the whole-corpus 'bm25' baseline is
#: plane routing / fusion, not a different ranker.
BM25_K1 = 1.5
BM25_B = 0.75

#: The standard RRF default (Cormack, Clarke & Buettcher, SIGIR 2009).  Not
#: swept for a favourable number -- see the module docstring.
RRF_K = 60

#: Mirrors s09_eval.contract.Budget().max_k (cutoffs frozen at 1/5/10/20).
#: Only the first RETURN_K entries of a ranking are ever scored by the
#: harness (contract.validate_ranking truncates there), so
#: returned_plane_counts below is measured over the SAME window, not over
#: whatever a retriever happens to return past it.  If the frozen budget
#: ever changes this constant has to move with it -- documented rather than
#: silently wrong.
RETURN_K = 20

#: The only Project-Twin planes this module can build a real per-file index
#: for.  See the module docstring for why type and presentation are absent.
FUSION_PLANES: Tuple[str, ...] = ("code", "data", "knowledge")


def _partition(universe: Sequence[Candidate]) -> Dict[str, List[Candidate]]:
    """Split the candidate universe into real per-plane document sets."""
    buckets: Dict[str, List[Candidate]] = {p: [] for p in FUSION_PLANES}
    for cand in universe:
        plane = plane_of(cand.path)
        if plane in buckets:
            buckets[plane].append(cand)
    return buckets


def _document(cand: Candidate, cache: TokenCache) -> Counter:
    """Token counts for one candidate: content plus path tokens.

    Identical shape to ``s09_eval.retrievers.Bm25._document`` (content-only
    would be a materially different, weaker baseline -- see s07/s09's own
    measured finding that path tokens carry real signal).  ``TokenCache``
    entries are shared, cached objects; copy before mutating, exactly as the
    baseline does, or the cache corrupts itself.
    """
    counts = cache.counts(cand.blob, cand.text)
    merged = Counter(counts)
    merged.update(word_tokens(cand.path))
    return merged


def _score_plane(
    query_terms: Sequence[str], candidates: Sequence[Candidate], cache: TokenCache
) -> List[Tuple[str, float]]:
    """Textbook BM25 over ONE plane's candidates only.

    Returns ``(path, score)`` pairs, best first, ties broken by path for a
    deterministic ranking.  This is the "scores in hand" object: every path
    in the return value carries the score this plane's own, independent
    term-frequency/IDF table produced for it -- nothing here has looked at
    any other plane yet.
    """
    q_terms = set(query_terms)
    if not q_terms or not candidates:
        return []
    docs: List[Tuple[str, Counter, int]] = []
    df: Counter = Counter()
    total_len = 0
    for cand in candidates:
        counts = _document(cand, cache)
        length = sum(counts.values())
        if not length:
            continue
        docs.append((cand.path, counts, length))
        total_len += length
        for term in q_terms:
            if term in counts:
                df[term] += 1
    if not docs:
        return []
    n = len(docs)
    avgdl = total_len / n
    idf = {
        term: math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
        for term in q_terms
        if df[term]
    }
    if not idf:
        return []
    scored: List[Tuple[float, str]] = []
    for path, counts, length in docs:
        score = 0.0
        for term, weight in idf.items():
            tf = counts.get(term, 0)
            if not tf:
                continue
            denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * length / avgdl)
            score += weight * (tf * (BM25_K1 + 1)) / denom
        if score > 0:
            scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(path, score) for score, path in scored]


def _rrf_combine(
    plane_rankings: Dict[str, List[Tuple[str, float]]], rrf_k: int = RRF_K
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion across REAL, separately-computed per-plane rankings.

    This function never recomputes a score from raw text and never sees a
    ``Candidate`` -- it only combines rank positions the per-plane scoring
    already produced (``_score_plane``, above).  A path missing from a
    plane's ranking (its BM25 score there was zero, or the plane had no
    candidates) contributes nothing from that plane; it is not treated as
    rank-infinity or penalised beyond simply not adding a term.
    """
    fused: Dict[str, float] = defaultdict(float)
    for _plane, ranked in plane_rankings.items():
        for rank, (path, _score) in enumerate(ranked, start=1):
            fused[path] += 1.0 / (rrf_k + rank)
    return sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))


def _new_counts() -> Dict[str, int]:
    return {plane: 0 for plane in FUSION_PLANES}


class FusionRetriever:
    """Role ``full`` / ``fusion``: cross-plane score fusion over code/data/knowledge.

    ``s10_kill/schema.py``'s own ``KNOWN_ROLES`` docstring anticipates this
    exact situation: ``"fusion"  # cross-plane fusion (may be the same
    system as full)``.  This is the only cross-plane-combining retriever
    anywhere in this program, so it stands for both roles when adapted --
    see ``s09_eval/to_s10.py``'s ``FUSION_RETRIEVER_ROLES`` and the README
    continuation for why that is a disclosed choice, not a duplication for
    statistical leverage (14.1 and 14.3 compare it against different
    baselines entirely).

    ``returned_plane_counts`` accumulates, per query variant, how many of
    the top ``RETURN_K`` returned paths landed in each plane -- across every
    case scored in one process.  This is real measurement, computed from the
    same ranking the harness scores, not a declared aspiration.
    """

    name = "fusion_rrf"

    def __init__(
        self,
        cache: Optional[TokenCache] = None,
        rrf_k: int = RRF_K,
        return_k: int = RETURN_K,
    ) -> None:
        # Each new retriever gets its own TokenCache rather than sharing the
        # harness's pre-warmed one: contract.load_retriever's module:attribute
        # spec zero-arg-constructs a bare class, so there is no seam to pass a
        # shared cache through the --retriever CLI path. A measured cost
        # (redundant tokenization work), not a correctness issue -- and this
        # program's own README says not to cite timings as meaningful.
        self.cache = cache if cache is not None else TokenCache()
        self.rrf_k = rrf_k
        self.return_k = return_k
        self.returned_plane_counts: Dict[str, Dict[str, int]] = {}
        #: the most recent call's real per-plane (path, score) rankings --
        #: kept for inspection and for test_fusion_retrievers.py to assert
        #: against, so "scores held in hand before combining" is checkable.
        self.last_plane_scores: Dict[str, List[Tuple[str, float]]] = {}

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        terms = word_tokens(query.text)
        buckets = _partition(universe)
        plane_scores = {
            plane: _score_plane(terms, cands, self.cache)
            for plane, cands in buckets.items()
            if cands
        }
        self.last_plane_scores = plane_scores
        fused = _rrf_combine(plane_scores, self.rrf_k)
        ranking = [path for path, _score in fused]
        self._tally(query.variant, ranking)
        return ranking

    def _tally(self, variant: str, ranking: Sequence[str]) -> None:
        counts = self.returned_plane_counts.setdefault(variant, _new_counts())
        for path in ranking[: self.return_k]:
            plane = plane_of(path)
            if plane in counts:
                counts[plane] += 1


class CodeOnlyRetriever:
    """Role ``code_only``: the code/AST plane alone, and nothing else.

    Reuses ``_score_plane`` -- the SAME BM25 pass ``FusionRetriever`` runs
    for its code-plane sub-index -- rather than a third reimplementation of
    BM25 in this module.  The only difference from ``FusionRetriever`` is
    that no other plane's ranking exists here to combine with.
    """

    name = "code_only_bm25"

    def __init__(self, cache: Optional[TokenCache] = None) -> None:
        self.cache = cache if cache is not None else TokenCache()

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        terms = word_tokens(query.text)
        code_docs = [c for c in universe if plane_of(c.path) == "code"]
        scored = _score_plane(terms, code_docs, self.cache)
        return [path for path, _score in scored]


class SeparateIndicesRetriever:
    """Role ``separate_indices``: the 14.3 comparator -- no fusion, by construction.

    Builds the SAME three per-plane indices ``FusionRetriever`` builds
    (identical ``_score_plane`` calls, identical buckets) and concatenates
    each plane's own top-``per_plane_k`` in a fixed, declared order.  No
    score from one plane is ever compared with a score from another --
    that is the invariant this baseline exists to hold, mirroring s08's
    ``UnionNoFusionRetriever`` (chosen over round-robin because s08 measured
    round-robin to be a slot-starvation artefact rather than an honest
    "no fusion" baseline: README, s08, withdrawn claim 1).

    Order is a declared prior, not hidden: s08 measured its own union arm
    scoring 491/600 with code first and 4/600 with code last on a code-heavy
    gold set.  ``order`` is therefore a constructor argument here too, and
    the default (code, data, knowledge) is stated plainly as a choice.
    """

    name = "separate_indices_bm25"

    def __init__(
        self,
        cache: Optional[TokenCache] = None,
        order: Sequence[str] = FUSION_PLANES,
        per_plane_k: int = RETURN_K,
    ) -> None:
        self.cache = cache if cache is not None else TokenCache()
        self.order = tuple(order)
        self.per_plane_k = per_plane_k
        self.returned_plane_counts: Dict[str, Dict[str, int]] = {}

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        terms = word_tokens(query.text)
        buckets = _partition(universe)
        out: List[str] = []
        for plane in self.order:
            scored = _score_plane(terms, buckets.get(plane, []), self.cache)
            out.extend(path for path, _score in scored[: self.per_plane_k])
        self._tally(query.variant, out)
        return out

    def _tally(self, variant: str, ranking: Sequence[str]) -> None:
        counts = self.returned_plane_counts.setdefault(variant, _new_counts())
        for path in ranking[:RETURN_K]:
            plane = plane_of(path)
            if plane in counts:
                counts[plane] += 1
