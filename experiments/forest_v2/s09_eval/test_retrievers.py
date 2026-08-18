"""Tests for the baselines: determinism, contract compliance, and the
property that makes each one a useful control."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import retrievers  # noqa: E402
from s09_eval.contract import Candidate, QueryView, validate_ranking  # noqa: E402
from s09_eval.tokens import TokenCache  # noqa: E402

UNIVERSE = [
    Candidate(path="daedalus/spine/effect_boundary.py", blob="b1", size=40,
              raw=b"class EffectBoundary:\n    def declare(self): ..."),
    Candidate(path="daedalus/providers/claude_cli.py", blob="b2", size=40,
              raw=b"broker runtime provider start stream"),
    Candidate(path="runs/council/room.md", blob="b3", size=40,
              raw=b"the council transcript mentions an undeclared sink"),
    Candidate(path="configs/schemas/matrix.json", blob="b4", size=40,
              raw=b"{\"title\": \"fault matrix contract\"}"),
]


def _query(text: str, variant: str = "raw", revision: str = "abc123") -> QueryView:
    return QueryView(case_id="c00", text=text, variant=variant, revision=revision)


def _all(retriever, query):
    ranking = retriever.rank(query, UNIVERSE)
    return validate_ranking(retriever.name, ranking, UNIVERSE, max_k=20)


def test_every_baseline_obeys_the_contract():
    cache = TokenCache()
    for retriever in retrievers.default_suite(cache):
        ranking = _all(retriever, _query("undeclared sink in the effect boundary"))
        assert len(set(ranking)) == len(ranking)


def test_random_is_deterministic_per_case_but_differs_across_cases():
    r = retrievers.RandomUniform()
    first = r.rank(_query("q"), UNIVERSE)
    assert first == r.rank(_query("q"), UNIVERSE)
    other = r.rank(QueryView("c07", "q", "raw", "abc123"), UNIVERSE)
    assert set(other) == set(first)
    assert other != first or len(UNIVERSE) < 3


def test_path_lexical_reads_the_path_and_not_the_body():
    r = retrievers.PathLexical()
    # "sink" appears only in a BODY, never in a path -> no path match at all
    assert _all(r, _query("sink")) == []
    # "boundary" appears only in a PATH -> that file ranks first
    assert _all(r, _query("boundary"))[0] == "daedalus/spine/effect_boundary.py"


def test_bm25_finds_a_term_that_exists_only_in_the_body():
    r = retrievers.Bm25(TokenCache())
    assert _all(r, _query("transcript"))[0] == "runs/council/room.md"


def test_content_only_ignores_a_term_that_exists_only_in_the_path():
    """The pair (bm25, bm25_content_only) has to actually isolate the path."""
    with_path = retrievers.Bm25(TokenCache())
    without_path = retrievers.Bm25ContentOnly(TokenCache())
    query = _query("providers")  # a directory name, absent from every body
    assert _all(with_path, query)[0] == "daedalus/providers/claude_cli.py"
    assert _all(without_path, query) == []


def test_recency_prior_never_reads_the_query_text():
    """Query-blindness is the point of this control, so it is asserted."""
    r = retrievers.RecencyPrior()
    r._order_cache[r.cache_key(r.repo, "rev1")] = {
        "runs/council/room.md": 1, "configs/schemas/matrix.json": 2
    }
    a = r.rank(_query("effect boundary", revision="rev1"), UNIVERSE)
    b = r.rank(_query("something entirely different", revision="rev1"), UNIVERSE)
    assert a == b == ["runs/council/room.md", "configs/schemas/matrix.json"]


def test_recency_cache_does_not_serve_one_repository_answer_to_another():
    """Isolation would leak straight through a revision-only cache key."""
    r = retrievers.RecencyPrior()
    live = r.cache_key(r.repo, "rev1")
    clone = r.cache_key("/tmp/preimage-clone", "rev1")
    assert live != clone
    r._order_cache[live] = {"runs/council/room.md": 1}
    assert r.rank(
        QueryView(case_id="c00", text="", variant="raw", revision="rev1",
                  repo="/tmp/preimage-clone"),
        UNIVERSE,
    ) == [], "the clone was served the live repository's cached history"


def test_recency_prior_returns_nothing_without_a_revision():
    assert retrievers.RecencyPrior().rank(_query("x", revision=""), UNIVERSE) == []


def test_retrievers_respect_the_content_budget():
    """A retriever cannot reach past the cap even if it wants the bytes."""
    tight = [
        Candidate(path="a.py", blob="c1", size=100, raw=b"visible hidden", content_budget=7)
    ]
    r = retrievers.Bm25(TokenCache())
    assert r.rank(_query("visible"), tight) == ["a.py"]
    assert r.rank(_query("hidden"), tight) == []


def test_empty_query_yields_an_empty_ranking_not_a_crash():
    for retriever in (retrievers.PathLexical(), retrievers.Bm25(TokenCache())):
        assert retriever.rank(_query(""), UNIVERSE) == []


def test_token_cache_reuses_by_blob_sha():
    cache = TokenCache()
    cache.counts("b1", lambda: "alpha beta")
    cache.counts("b1", lambda: "totally different text")
    assert cache.hits == 1 and cache.misses == 1
    assert cache.counts("b1", lambda: "")["alpha"] == 1
