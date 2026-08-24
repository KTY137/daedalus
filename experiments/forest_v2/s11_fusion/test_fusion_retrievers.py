"""Checks for the s11 fusion retrievers.

Same convention every other slice in this program uses: put
``experiments/forest_v2`` on ``sys.path`` and reach siblings as top-level
packages, so this test file runs standalone (``pytest
experiments/forest_v2/s11_fusion``) as well as from the repository root.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from s09_eval.contract import Candidate, QueryView  # noqa: E402
from s09_eval.tokens import TokenCache  # noqa: E402
from s11_fusion import fusion_retrievers as fr  # noqa: E402


def _cand(path: str, text: str) -> Candidate:
    return Candidate(path=path, blob=path, size=len(text), raw=text.encode("utf-8"))


def _query(text: str, variant: str = "raw") -> QueryView:
    return QueryView(case_id="t", text=text, variant=variant, revision="", repo="")


# ------------------------------------------------------------- _rrf_combine


def test_rrf_combine_matches_the_formula_by_hand():
    """A document reinforced by a second plane beats one that is merely the
    single best result in one plane -- the defining behaviour of fusion.

    plane_rankings is synthetic (no BM25, no candidates): this isolates the
    combination arithmetic from the scoring arithmetic.
    """
    plane_rankings = {
        "code": [("a", 10.0), ("b", 5.0)],
        "data": [("b", 8.0)],
        "knowledge": [("c", 3.0)],
    }
    fused = fr._rrf_combine(plane_rankings, rrf_k=60)
    scores = dict(fused)
    assert scores["a"] == 1.0 / 61
    assert scores["b"] == 1.0 / 62 + 1.0 / 61
    assert scores["c"] == 1.0 / 61
    # b is reinforced by two planes and wins outright, despite never being
    # the top-ranked candidate in either one on its own.
    ranked_paths = [path for path, _ in fused]
    assert ranked_paths[0] == "b"
    # a and c tie at 1/61 each; deterministic tie-break is alphabetical.
    assert ranked_paths[1:] == ["a", "c"]


def test_rrf_combine_ignores_a_plane_that_never_returned_the_document():
    """A path absent from a plane's ranking contributes nothing from it --
    not a penalty, not an implicit worst-rank."""
    fused = dict(fr._rrf_combine({"code": [("x", 1.0)], "data": []}))
    assert fused == {"x": 1.0 / 61}


# --------------------------------------------------------- _score_plane / IDF


def test_per_plane_idf_differs_from_a_joint_pooled_index():
    """The core "not a joint index" claim, tested directly at the scoring
    layer rather than inferred from a final ranking.

    A joint single BM25 index shares ONE document-frequency table for a term
    across every document regardless of plane. Real per-plane sub-indices do
    not: the same term gets a DIFFERENT idf depending on which bucket it is
    scored in. If ``_score_plane`` secretly pooled everything into one table
    (the defect this whole module exists to avoid), this test would fail --
    verified by hand: temporarily replacing the ``candidates`` argument in
    both calls below with the same pooled list collapses the two idf values
    to one number and turns this assertion red.
    """
    cache = TokenCache()
    knowledge_only = [
        _cand("docs/k1.md", "widget appears here one time"),
        _cand("docs/k2.md", "nothing related to the query"),
        _cand("docs/k3.md", "still nothing here at all"),
    ]
    code_heavy = [
        _cand("pkg/a.py", "widget widget widget widget widget"),
        _cand("pkg/b.py", "widget appears once"),
        _cand("pkg/c.py", "widget appears once too"),
    ]
    terms = ["widget"]

    knowledge_scores = dict(fr._score_plane(terms, knowledge_only, cache))
    pooled_scores = dict(fr._score_plane(terms, knowledge_only + code_heavy, cache))

    # "widget" is rare within the knowledge-only bucket (1 of 3 documents)
    # and common within the pooled bucket (4 of 6) -- a joint index cannot
    # tell these two situations apart for the SAME document; a real
    # per-plane index must.
    assert knowledge_scores["docs/k1.md"] != pooled_scores["docs/k1.md"]
    assert knowledge_scores["docs/k1.md"] > pooled_scores["docs/k1.md"], (
        "widget is rarer (higher idf) inside the knowledge-only bucket than "
        "inside the pooled bucket, so k1's real per-plane score must be higher"
    )


# ---------------------------------------------------- fusion vs concatenation


def test_fusion_interleaves_by_confidence_while_concatenation_uses_a_fixed_order():
    """The concrete, mechanistic difference between real fusion and the
    no-fusion comparator, demonstrated rather than asserted.

    Two code-plane documents match the query (one strongly, one weakly) and
    one data-plane document matches it once, as the plane's only document
    (so it is trivially that plane's rank 1). ``SeparateIndicesRetriever``
    concatenates in a FIXED plane order: both code documents -- strong AND
    weak -- always precede the data document, regardless of how the data
    document's own confidence compares to code's second-best.
    ``FusionRetriever`` combines by RANK POSITION per plane: the data
    document (rank 1 in its plane) and the strong code document (rank 1 in
    its plane) tie for the top RRF score, and the weak code document (rank 2
    in its plane) drops BELOW the data document -- a rank-based interleaving
    a fixed concatenation order cannot produce.
    """
    universe = [
        _cand("pkg/strong.py", "alpha alpha alpha"),
        _cand("pkg/weak.py", "alpha filler filler filler filler"),
        _cand("data/match.json", "alpha alpha"),
    ]
    query = _query("alpha")

    fusion = fr.FusionRetriever().rank(query, universe)
    concat = fr.SeparateIndicesRetriever().rank(query, universe)

    assert fusion.index("pkg/weak.py") > fusion.index("data/match.json"), (
        "fusion: the data plane's only (rank-1) match outranks code's "
        "second-best match"
    )
    assert concat.index("pkg/weak.py") < concat.index("data/match.json"), (
        "concatenation: code's whole block, weak match included, precedes "
        "data's block regardless of confidence"
    )


# --------------------------------------------------------------- code_only


def test_code_only_never_returns_a_non_code_path():
    universe = [
        _cand("pkg/mod.py", "shared term here"),
        _cand("docs/notes.md", "shared term here too"),
        _cand("data/x.json", "shared term here as well"),
    ]
    out = fr.CodeOnlyRetriever().rank(_query("shared term"), universe)
    assert out == ["pkg/mod.py"]


# ---------------------------------------------------------- separate_indices


def test_separate_indices_output_is_grouped_strictly_by_declared_order():
    universe = [
        _cand("pkg/a.py", "term term term"),
        _cand("pkg/b.py", "term"),
        _cand("data/x.json", "term term term term term"),  # highest raw score
        _cand("docs/y.md", "term term"),
    ]
    out = fr.SeparateIndicesRetriever(order=("code", "data", "knowledge")).rank(
        _query("term"), universe
    )
    # data/x.json would win on raw BM25 score alone, but concatenation order
    # is code first: no score comparison ever happens across the boundary.
    code_positions = [out.index(p) for p in ("pkg/a.py", "pkg/b.py")]
    other_positions = [out.index(p) for p in ("data/x.json", "docs/y.md")]
    assert max(code_positions) < min(other_positions)


# ----------------------------------------------------- returned_plane_counts


def test_returned_plane_counts_accumulate_per_variant_across_calls():
    universe = [
        _cand("pkg/a.py", "alpha"),
        _cand("data/b.json", "alpha"),
    ]
    retriever = fr.FusionRetriever()
    retriever.rank(_query("alpha", "raw"), universe)
    retriever.rank(_query("alpha", "raw"), universe)  # same query again: must accumulate, not reset
    retriever.rank(_query("alpha", "scrubbed"), universe)

    raw_counts = retriever.returned_plane_counts["raw"]
    assert raw_counts["code"] == 2  # pkg/a.py returned once per call, two raw calls
    assert raw_counts["data"] == 2
    scrubbed_counts = retriever.returned_plane_counts["scrubbed"]
    assert scrubbed_counts["code"] == 1
    assert scrubbed_counts["data"] == 1
    assert scrubbed_counts is not raw_counts  # tracked separately per variant


def test_returned_plane_counts_are_capped_at_return_k():
    universe = [_cand(f"pkg/f{i}.py", "term") for i in range(30)]
    retriever = fr.FusionRetriever(return_k=5)
    retriever.rank(_query("term"), universe)
    assert retriever.returned_plane_counts["raw"]["code"] == 5


# ------------------------------------------------------------ scores in hand


def test_fusion_retriever_holds_real_per_plane_scores_before_combining():
    universe = [
        _cand("pkg/a.py", "shared query term"),
        _cand("data/b.json", "shared query term"),
        _cand("docs/c.md", "shared query term"),
    ]
    retriever = fr.FusionRetriever()
    retriever.rank(_query("shared query term"), universe)
    # all three planes independently scored the shared term -- three
    # separate, non-empty, real BM25 rankings held before any RRF happened.
    assert set(retriever.last_plane_scores) == {"code", "data", "knowledge"}
    for plane, ranked in retriever.last_plane_scores.items():
        assert ranked, f"{plane} produced no real per-plane ranking"
        assert all(score > 0 for _path, score in ranked)


# ------------------------------------------------------------ scope honesty


def test_type_and_presentation_are_never_indexed():
    assert "type" not in fr.FUSION_PLANES
    assert "presentation" not in fr.FUSION_PLANES
    universe = [
        _cand("pkg/mod.py", "widget"),
        _cand("site/index.html", "widget"),  # presentation plane -- not a Twin plane
    ]
    fusion_out = fr.FusionRetriever().rank(_query("widget"), universe)
    concat_out = fr.SeparateIndicesRetriever().rank(_query("widget"), universe)
    code_only_out = fr.CodeOnlyRetriever().rank(_query("widget"), universe)
    assert "site/index.html" not in fusion_out
    assert "site/index.html" not in concat_out
    assert "site/index.html" not in code_only_out
