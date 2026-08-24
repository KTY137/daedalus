"""Pure, receipt-bearing local baselines for the tensor diagnostic harness.

All five arms receive the same budget-visible query and candidate texts as the
tensor arms.  They are deterministic for a frozen integer seed, retain a score
for every candidate, and expose only unverified retrieval proposals.

``recency_prior`` is deliberately supplied a caller-asserted path order by
the evaluator.  ``Candidate`` carries no history, and deriving "recency" from
a path, blob hash, or current checkout would either fabricate the control or
cross the pre-image boundary.  The order is included in the benchmark corpus
digest by :class:`benchmark.BenchmarkCase`, which proves exactly what was
used but not that an external history issuer derived it from the pre-image.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from experiments.forest_v2.s09_eval.contract import Candidate, ContractViolation, QueryView
from experiments.forest_v2.s09_eval.taskset import plane_of
from experiments.forest_v2.s09_eval.tokens import path_tokens, word_tokens

from .encoding import canonical_source_digest


BASELINE_RECEIPT_SCHEMA = "forest-v2.tensor-baseline-score-receipt/1"
BASELINE_BACKEND_ID = (
    "forest-v2.local-deterministic-baselines-"
    "bm25-k1-1.5-b-0.75-rrf-k60-code-data-knowledge/1"
)
DEFAULT_BASELINE_CACHE_ENTRIES = 20_000

# Literal copies of the audited s09/s11 controls.  Importing live constants
# would let a later baseline module revision silently change results while
# this experiment still emitted the same backend ID.  Tests pin these copies
# to the canonical implementations available at freeze time.
BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60
FUSION_PLANES = ("code", "data", "knowledge")

QueryReceiptKey = tuple[str, str, str, str]


def baseline_query_key(query: QueryView) -> QueryReceiptKey:
    """Return the exact evaluator-visible identity used by baseline receipts."""

    case_id = query.case_id
    variant = query.variant
    text = query.text
    revision = query.revision
    if type(case_id) is not str or not case_id:
        raise ContractViolation("query case_id must be a non-empty string")
    if type(variant) is not str or not variant:
        raise ContractViolation("query variant must be a non-empty string")
    if type(text) is not str:
        raise ContractViolation("query text must be a string")
    if type(revision) is not str or not revision:
        raise ContractViolation("query revision must be a non-empty string")
    return (case_id, variant, revision, canonical_source_digest(text))


@dataclass(frozen=True)
class BaselineCandidateInputReceipt:
    """Identity of one exact candidate view made available to a baseline."""

    path: str
    blob: str
    text_digest: str
    text_characters: int
    text_bytes: int

    @property
    def input_id(self) -> tuple[str, str, str]:
        return (self.path, self.blob, self.text_digest)


@dataclass(frozen=True)
class BaselineScoreReceipt:
    """Replay-oriented baseline receipt; it grants no evidence authority."""

    retriever: str
    score_kind: str
    query_case_id: str
    query_variant: str
    revision: str
    query_text_digest: str
    candidate_inputs: tuple[BaselineCandidateInputReceipt, ...]
    scores: tuple[tuple[str, float], ...]
    seed: int
    input_scalar_budget: int = 0
    dense_scalars_per_tensor: int = 0
    backend_id: str = BASELINE_BACKEND_ID
    schema: str = BASELINE_RECEIPT_SCHEMA
    proposal_only: bool = True
    authority: str = "unverified-retrieval-proposal"

    @property
    def query_input_id(self) -> QueryReceiptKey:
        return (
            self.query_case_id,
            self.query_variant,
            self.revision,
            self.query_text_digest,
        )

    @property
    def input_ids(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(item.input_id for item in self.candidate_inputs)


@dataclass(frozen=True)
class _PreparedCandidate:
    candidate: Candidate
    text: str
    text_digest: str
    tokens: tuple[str, ...]


BaselineCacheKey = tuple[str, str, str, str]


class BaselineCandidateCache:
    """Caller-owned LRU for exact visible text and canonical lexical tokens."""

    def __init__(self, max_entries: int = DEFAULT_BASELINE_CACHE_ENTRIES) -> None:
        if isinstance(max_entries, bool) or type(max_entries) is not int or max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._entries: "OrderedDict[BaselineCacheKey, _PreparedCandidate]" = OrderedDict()
        self._blob_digests: dict[str, str] = {}

    def prepare(
        self, candidate: Candidate, text: str, *, revision: str
    ) -> _PreparedCandidate:
        if not isinstance(candidate, Candidate):
            raise ContractViolation("baseline candidate must be an s09 Candidate")
        if type(candidate.path) is not str or not candidate.path:
            raise ContractViolation("candidate path must be a non-empty string")
        if type(candidate.blob) is not str or not candidate.blob:
            raise ContractViolation("candidate blob must be a non-empty string")
        if type(text) is not str:
            raise ContractViolation("Candidate.text() must return a string")
        if type(revision) is not str or not revision:
            raise ContractViolation("candidate revision must be a non-empty string")
        digest = canonical_source_digest(text)
        prior_digest = self._blob_digests.get(candidate.blob)
        if prior_digest is not None and prior_digest != digest:
            raise ContractViolation("one candidate blob names different visible text")
        self._blob_digests[candidate.blob] = digest
        key = (revision, candidate.path, candidate.blob, digest)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached
        prepared = _PreparedCandidate(
            candidate=candidate,
            text=text,
            text_digest=digest,
            tokens=tuple(word_tokens(text)),
        )
        self._entries[key] = prepared
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return prepared


def _bm25_scores(
    query_terms: Sequence[str], candidates: Sequence[_PreparedCandidate]
) -> dict[str, float]:
    """Canonical s09 BM25 formula, returning explicit zero-score ties too."""

    terms = set(query_terms)
    scores = {item.candidate.path: 0.0 for item in candidates}
    if not terms or not candidates:
        return scores
    documents: list[tuple[str, Counter[str], int]] = []
    document_frequency: Counter[str] = Counter()
    total_length = 0
    for item in candidates:
        counts: Counter[str] = Counter(item.tokens)
        counts.update(word_tokens(item.candidate.path))
        length = sum(counts.values())
        if not length:
            continue
        documents.append((item.candidate.path, counts, length))
        total_length += length
        for term in terms:
            if term in counts:
                document_frequency[term] += 1
    if not documents:
        return scores
    count = len(documents)
    average_length = total_length / count
    inverse_frequency = {
        term: math.log(
            1.0 + (count - document_frequency[term] + 0.5)
            / (document_frequency[term] + 0.5)
        )
        for term in terms
        if document_frequency[term]
    }
    for path, counts, length in documents:
        value = 0.0
        for term, weight in inverse_frequency.items():
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            denominator = frequency + BM25_K1 * (
                1.0 - BM25_B + BM25_B * length / average_length
            )
            value += weight * (frequency * (BM25_K1 + 1.0)) / denominator
        scores[path] = value
    return scores


def _rank_scores(scores: Mapping[str, float]) -> tuple[tuple[str, float], ...]:
    if any(not math.isfinite(value) for value in scores.values()):
        raise ContractViolation("baseline produced a non-finite score")
    return tuple(sorted(scores.items(), key=lambda item: (-item[1], item[0])))


class _BaselineRetriever:
    name = "baseline_abstract"
    score_kind = "abstract"

    def __init__(
        self,
        seed: int,
        *,
        candidate_cache: BaselineCandidateCache | None = None,
        recency_by_query: Mapping[QueryReceiptKey, tuple[str, ...]] | None = None,
    ) -> None:
        if isinstance(seed, bool) or type(seed) is not int:
            raise ValueError("baseline seed must be an integer")
        self.seed = seed
        self.candidate_cache = (
            candidate_cache
            if candidate_cache is not None
            else BaselineCandidateCache()
        )
        self.recency_by_query = dict(recency_by_query or {})
        self.score_receipts: dict[QueryReceiptKey, BaselineScoreReceipt] = {}

    def _scores(
        self,
        query: QueryView,
        key: QueryReceiptKey,
        candidates: tuple[_PreparedCandidate, ...],
    ) -> Mapping[str, float]:
        raise NotImplementedError

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> list[str]:
        key = baseline_query_key(query)
        seen: set[str] = set()
        prepared: list[_PreparedCandidate] = []
        for candidate in sorted(universe, key=lambda item: item.path):
            if candidate.path in seen:
                raise ContractViolation(
                    f"candidate universe contains duplicate path {candidate.path!r}"
                )
            seen.add(candidate.path)
            text = candidate.text()
            prepared.append(
                self.candidate_cache.prepare(candidate, text, revision=query.revision)
            )
        if not prepared:
            raise ContractViolation("baseline candidate universe must not be empty")
        prepared_tuple = tuple(prepared)
        ranked_scores = _rank_scores(self._scores(query, key, prepared_tuple))
        paths = tuple(item.candidate.path for item in prepared_tuple)
        if set(path for path, _ in ranked_scores) != set(paths) or len(ranked_scores) != len(paths):
            raise ContractViolation("baseline must score every candidate exactly once")
        receipt = BaselineScoreReceipt(
            retriever=self.name,
            score_kind=self.score_kind,
            query_case_id=query.case_id,
            query_variant=query.variant,
            revision=query.revision,
            query_text_digest=key[3],
            candidate_inputs=tuple(
                BaselineCandidateInputReceipt(
                    path=item.candidate.path,
                    blob=item.candidate.blob,
                    text_digest=item.text_digest,
                    text_characters=len(item.text),
                    text_bytes=len(item.text.encode("utf-8")),
                )
                for item in prepared_tuple
            ),
            scores=ranked_scores,
            seed=self.seed,
        )
        self.score_receipts[key] = receipt
        # Canonical s09 lexical and s11 fusion controls do not turn an
        # unmatched candidate into a retrieval hit merely to fill a cutoff.
        # Keep explicit zero scores in the replay receipt, but expose only
        # positive/reachable documents as the ranking.  Random assigns every
        # candidate a positive positional score and therefore remains a full
        # permutation; recency returns exactly its supplied pre-image paths.
        return [path for path, score in ranked_scores if score > 0.0]

    def score_receipt(self, query: QueryView) -> BaselineScoreReceipt:
        try:
            return self.score_receipts[baseline_query_key(query)]
        except KeyError as exc:
            raise KeyError("query has not been ranked by this baseline") from exc


class Bm25Baseline(_BaselineRetriever):
    name = "bm25"
    score_kind = "bm25_content_plus_path"

    def _scores(self, query, key, candidates):
        return _bm25_scores(word_tokens(query.text), candidates)


class RandomUniformBaseline(_BaselineRetriever):
    name = "random_uniform"
    score_kind = "deterministic_s09_uniform_shuffle"

    def _scores(self, query, key, candidates):
        # Match the canonical s09 random control on the uniquely path-sorted
        # common universe.  Ranking is query-content-blind and seeded per case;
        # positional scores only let the shared receipt machinery retain the
        # exact permutation without introducing ties.
        digest = hashlib.sha256(
            f"{self.seed}:{query.case_id}".encode("utf-8")
        ).hexdigest()
        rng = random.Random(int(digest[:16], 16))
        paths = [item.candidate.path for item in candidates]
        rng.shuffle(paths)
        count = len(paths)
        return {path: float(count - rank) for rank, path in enumerate(paths)}


class PathLexicalBaseline(_BaselineRetriever):
    name = "path_lexical"
    score_kind = "path_token_overlap"

    def _scores(self, query, key, candidates):
        query_terms = set(word_tokens(query.text))
        scores: dict[str, float] = {}
        for item in candidates:
            tokens = path_tokens(item.candidate.path)
            overlap = len(query_terms & tokens)
            scores[item.candidate.path] = (
                overlap / math.sqrt(len(tokens)) if overlap and tokens else 0.0
            )
        return scores


class RecencyPriorBaseline(_BaselineRetriever):
    name = "recency_prior"
    score_kind = "caller_asserted_recency_order"

    def _scores(self, query, key, candidates):
        if key not in self.recency_by_query:
            raise ContractViolation("recency_prior has no caller-asserted order")
        order = self.recency_by_query[key]
        known = {item.candidate.path for item in candidates}
        if len(set(order)) != len(order) or set(order) - known:
            raise ContractViolation("recency order is duplicated or outside the universe")
        rank_by_path = {path: rank for rank, path in enumerate(order, 1)}
        return {
            path: 1.0 / rank_by_path[path] if path in rank_by_path else 0.0
            for path in known
        }


class FusionRrfBaseline(_BaselineRetriever):
    """Canonical s11 plane partition + independent BM25 + RRF(k=60)."""

    name = "fusion_rrf"
    score_kind = "s11_per_plane_bm25_rrf"

    def _scores(self, query, key, candidates):
        buckets: dict[str, list[_PreparedCandidate]] = {
            plane: [] for plane in FUSION_PLANES
        }
        for item in candidates:
            plane = plane_of(item.candidate.path)
            if plane in buckets:
                buckets[plane].append(item)
        query_terms = word_tokens(query.text)
        fused: defaultdict[str, float] = defaultdict(float)
        for plane in FUSION_PLANES:
            plane_scores = _bm25_scores(query_terms, buckets[plane])
            positive = [
                (path, score)
                for path, score in _rank_scores(plane_scores)
                if score > 0.0
            ]
            for rank, (path, _score) in enumerate(positive, 1):
                fused[path] += 1.0 / (RRF_K + rank)
        return {
            item.candidate.path: fused.get(item.candidate.path, 0.0)
            for item in candidates
        }


BASELINE_RETRIEVER_TYPES = (
    Bm25Baseline,
    RandomUniformBaseline,
    PathLexicalBaseline,
    RecencyPriorBaseline,
    FusionRrfBaseline,
)


__all__ = [
    "BASELINE_BACKEND_ID",
    "BASELINE_RECEIPT_SCHEMA",
    "BASELINE_RETRIEVER_TYPES",
    "BM25_B",
    "BM25_K1",
    "BaselineCandidateCache",
    "BaselineCandidateInputReceipt",
    "BaselineScoreReceipt",
    "Bm25Baseline",
    "FusionRrfBaseline",
    "FUSION_PLANES",
    "PathLexicalBaseline",
    "RandomUniformBaseline",
    "RecencyPriorBaseline",
    "RRF_K",
    "baseline_query_key",
]
