"""Canonical-equivalence and adversarial tests for local baseline arms."""
from __future__ import annotations

from dataclasses import replace

import pytest

from experiments.forest_v2.s09_eval.contract import (
    Candidate,
    ContractViolation,
    QueryView,
)
from experiments.forest_v2.s09_eval.retrievers import (
    Bm25 as CanonicalBm25,
    PathLexical as CanonicalPathLexical,
    RandomUniform as CanonicalRandomUniform,
)
from experiments.forest_v2.s11_fusion.fusion_retrievers import (
    BM25_B as CANONICAL_BM25_B,
    BM25_K1 as CANONICAL_BM25_K1,
    FUSION_PLANES as CANONICAL_FUSION_PLANES,
    FusionRetriever as CanonicalFusionRetriever,
    RRF_K as CANONICAL_RRF_K,
)
from experiments.forest_v2.tensor_embeddings.baseline_retrievers import (
    BASELINE_BACKEND_ID,
    BASELINE_RETRIEVER_TYPES,
    BM25_B,
    BM25_K1,
    FUSION_PLANES,
    RRF_K,
    BaselineCandidateCache,
    Bm25Baseline,
    FusionRrfBaseline,
    PathLexicalBaseline,
    RandomUniformBaseline,
    RecencyPriorBaseline,
    baseline_query_key,
)


def _candidate(path: str, blob: str, text: str) -> Candidate:
    raw = text.encode("utf-8")
    return Candidate(
        path=path,
        blob=blob,
        size=len(raw),
        raw=raw,
        content_budget=len(raw),
    )


def _universe() -> tuple[Candidate, ...]:
    return (
        _candidate("src/parser.py", "blob-parser", "parse record value schema"),
        _candidate("src/storage.py", "blob-storage-code", "storage index migration"),
        _candidate("schemas/record.json", "blob-record", "record schema data"),
        _candidate("docs/storage.md", "blob-storage-doc", "storage migration guide"),
        _candidate("types/record.pyi", "blob-type", "record protocol type"),
        _candidate("web/index.html", "blob-web", "presentation shell"),
    )


def _query() -> QueryView:
    return QueryView(
        case_id="case-1",
        text="parse record storage",
        variant="scrubbed",
        revision="preimage-revision",
        repo="this-path-must-never-be-opened",
    )


def _recency() -> dict[tuple[str, str, str, str], tuple[str, ...]]:
    return {
        baseline_query_key(_query()): (
            "docs/storage.md",
            "schemas/record.json",
            "src/parser.py",
        )
    }


def test_local_baseline_parameters_are_frozen_to_the_audited_s11_control() -> None:
    assert (BM25_K1, BM25_B, RRF_K, FUSION_PLANES) == (
        CANONICAL_BM25_K1,
        CANONICAL_BM25_B,
        CANONICAL_RRF_K,
        CANONICAL_FUSION_PLANES,
    )
    assert "bm25-k1-1.5-b-0.75-rrf-k60-code-data-knowledge" in BASELINE_BACKEND_ID


def test_local_baselines_match_canonical_positive_rankings_and_random_shuffle() -> None:
    query = _query()
    universe = tuple(sorted(_universe(), key=lambda item: item.path))
    seed = 23

    local_bm25 = Bm25Baseline(seed).rank(query, universe)
    canonical_bm25 = CanonicalBm25().rank(query, universe)
    assert local_bm25 == canonical_bm25

    local_path = PathLexicalBaseline(seed).rank(query, universe)
    canonical_path = CanonicalPathLexical().rank(query, universe)
    assert local_path == canonical_path

    local_random = RandomUniformBaseline(seed).rank(query, universe)
    canonical_random = CanonicalRandomUniform(seed=str(seed)).rank(query, universe)
    assert local_random == canonical_random

    local_fusion = FusionRrfBaseline(seed).rank(query, universe)
    canonical_fusion = CanonicalFusionRetriever().rank(query, universe)
    assert local_fusion == canonical_fusion


def test_all_five_baselines_are_complete_proposal_only_and_share_exact_inputs() -> None:
    query = _query()
    universe = _universe()
    cache = BaselineCandidateCache()
    receipts = []
    rankings = {}
    for kind in BASELINE_RETRIEVER_TYPES:
        retriever = kind(
            seed=11,
            candidate_cache=cache,
            recency_by_query=_recency(),
        )
        ranking = retriever.rank(query, universe)
        receipt = retriever.score_receipt(query)
        rankings[kind.name] = ranking
        receipts.append(receipt)
        assert len(ranking) == len(set(ranking))
        assert set(ranking) <= {candidate.path for candidate in universe}
        assert len(receipt.scores) == len(universe)
        assert receipt.input_scalar_budget == 0
        assert receipt.dense_scalars_per_tensor == 0
        assert receipt.backend_id == BASELINE_BACKEND_ID
        assert receipt.proposal_only is True
        assert receipt.authority == "unverified-retrieval-proposal"

    reference = receipts[0]
    assert all(receipt.query_input_id == reference.query_input_id for receipt in receipts)
    assert all(receipt.input_ids == reference.input_ids for receipt in receipts)
    assert rankings["recency_prior"][:3] == [
        "docs/storage.md",
        "schemas/record.json",
        "src/parser.py",
    ]
    assert len(rankings["recency_prior"]) == 3


def test_zero_score_candidates_never_become_fake_lexical_or_fusion_hits() -> None:
    query = replace(_query(), text="completely unmatched vocabulary")
    universe = _universe()
    for kind in (Bm25Baseline, PathLexicalBaseline, FusionRrfBaseline):
        retriever = kind(11)
        assert retriever.rank(query, universe) == []
        receipt = retriever.score_receipt(query)
        assert len(receipt.scores) == len(universe)
        assert all(score == 0.0 for _path, score in receipt.scores)


def test_random_changes_with_seed_while_query_aware_and_prior_controls_do_not() -> None:
    query = _query()
    universe = _universe()
    assert RandomUniformBaseline(11).rank(query, universe) != RandomUniformBaseline(
        23
    ).rank(query, universe)
    for kind in (Bm25Baseline, PathLexicalBaseline, FusionRrfBaseline):
        assert kind(11).rank(query, universe) == kind(23).rank(query, universe)
    assert RecencyPriorBaseline(11, recency_by_query=_recency()).rank(
        query, universe
    ) == RecencyPriorBaseline(23, recency_by_query=_recency()).rank(query, universe)


def test_recency_requires_evaluator_supplied_preimage_order_and_rejects_poisoning() -> None:
    query = _query()
    universe = _universe()
    with pytest.raises(ContractViolation, match="caller-asserted order"):
        RecencyPriorBaseline(11).rank(query, universe)

    poisoned = {baseline_query_key(query): ("ghost.py",)}
    with pytest.raises(ContractViolation, match="outside the universe"):
        RecencyPriorBaseline(11, recency_by_query=poisoned).rank(query, universe)

    duplicated = {baseline_query_key(query): ("src/parser.py", "src/parser.py")}
    with pytest.raises(ContractViolation, match="duplicated"):
        RecencyPriorBaseline(11, recency_by_query=duplicated).rank(query, universe)


def test_shared_cache_refuses_one_blob_naming_different_visible_text() -> None:
    query = _query()
    original = _candidate("src/a.py", "same-blob", "first visible text")
    forged = replace(
        original,
        path="src/b.py",
        raw=b"second visible text",
        size=len(b"second visible text"),
        content_budget=len(b"second visible text"),
    )
    cache = BaselineCandidateCache()
    Bm25Baseline(11, candidate_cache=cache).rank(query, (original,))
    with pytest.raises(ContractViolation, match="different visible text"):
        Bm25Baseline(11, candidate_cache=cache).rank(query, (forged,))
