"""Self-tests for the s07 BM25 baseline.

Run directly::

    python -m pytest experiments/forest_v2/s07_bm25/test_bm25_index.py -q

Two kinds of test live here on purpose:

* hermetic tests over synthetic corpora, which pin the scoring behaviour
  (saturation, length normalisation, idf, determinism) and never move when the
  repository moves;
* a small **known-hit self-test** over two real subtrees of this repository.
  It is the only thing that can catch "the maths is right, the retrieval is
  useless".  It asserts rank-1 for targets whose filename *and* body are about
  the query, and it is deliberately scoped to subtrees so it stays sub-second.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bm25_index import (  # noqa: E402
    SCHEMA,
    BM25Index,
    IndexConfig,
    tokenize,
    token_counts,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# Contamination firewall for the known-hit tests, expressed relative to the
# `experiments/forest_v2` subtree.  This file, the measurement script and the
# slice README all quote the query strings verbatim; left in the corpus they
# win their own queries.  Documenting an evaluation contaminates it just as
# thoroughly as coding it does.
FOREST_V2_QUERY_CARRIERS = frozenset(
    {
        "README.md",
        "s07_bm25/measure_bm25.py",
        "s07_bm25/test_bm25_index.py",
    }
)


# --------------------------------------------------------------- tokenizer


def test_tokenize_splits_snake_and_camel_and_keeps_the_whole_identifier():
    assert tokenize("iron_plan_guard") == ["ironplanguard", "iron", "plan", "guard"]
    # "25" is a sub-token with no letter, so it is dropped -- the whole
    # identifier still carries it.
    assert tokenize("BM25Index") == ["bm25index", "bm", "index"]
    assert tokenize("HTTPServerHandler") == [
        "httpserverhandler",
        "http",
        "server",
        "handler",
    ]


def test_tokenize_drops_short_and_letterless_tokens():
    # "a" is below min_token_len; "42" and "0xdeadbeef"-style digit runs carry
    # no vocabulary, so anything without a letter is dropped.
    assert tokenize("a budget of 42") == ["budget", "of"]
    assert tokenize("12345") == []
    assert tokenize("v2") == ["v2"]


def _reference_expand(raw: str, min_token_len: int = 2) -> list[str]:
    """The unoptimised expansion: always camel-split, never take a fast path."""
    import re

    out: list[str] = []
    whole = raw.replace("_", "").lower()
    if len(whole) >= min_token_len and re.search(r"[A-Za-z]", whole):
        out.append(whole)
    parts: list[str] = []
    for chunk in raw.split("_"):
        if chunk:
            parts.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", chunk))
    if len(parts) > 1:
        for part in parts:
            low = part.lower()
            if len(low) >= min_token_len and re.search(r"[A-Za-z]", low):
                out.append(low)
    return out


def test_lowercase_fast_path_matches_the_unoptimised_expansion():
    words = (
        "hello",
        "hello123",
        "123",
        "_",
        "__init__",
        "aB",
        "AB",
        "a_b",
        "BM25Index",
        "HTTPServerHandler",
        "iron_plan_guard",
        "v2",
        "snake_Case_Mix",
        "trailing_",
        "ALLCAPS",
    )
    for word in words:
        assert tokenize(word) == _reference_expand(word), word


def test_token_counts_is_equivalent_to_counting_tokenize():
    from collections import Counter

    sample = (
        "def build_index(root): return BM25Index.build(root)\n"
        "# build_index build_index HTTPServer http_server v2 v2 a 7\n"
    )
    assert token_counts(sample) == Counter(tokenize(sample))


# ------------------------------------------------------------------ scoring


def _tiny_index(**kwargs) -> BM25Index:
    docs = {
        "a.txt": "budget budget budget ledger",
        "b.txt": "budget ledger",
        "c.txt": "ledger only here",
        "d.txt": "nothing relevant at all",
    }
    return BM25Index.from_documents(docs, IndexConfig(path_weight=0, **kwargs))


def test_more_matching_terms_outranks_fewer():
    hits = _tiny_index().search("budget ledger", k=10)
    assert [hit.path for hit in hits][:2] == ["a.txt", "b.txt"]
    assert hits[0].score > hits[1].score
    assert hits[0].matched_terms == ("budget", "ledger")


def test_documents_without_any_query_term_are_absent():
    paths = [hit.path for hit in _tiny_index().search("budget", k=10)]
    assert paths == ["a.txt", "b.txt"]
    assert "d.txt" not in paths


def test_length_normalisation_prefers_the_shorter_document():
    docs = {
        "short.txt": "ledger",
        "long.txt": "ledger " + "filler " * 200,
    }
    index = BM25Index.from_documents(docs, IndexConfig(path_weight=0))
    hits = index.search("ledger", k=5)
    assert [hit.path for hit in hits] == ["short.txt", "long.txt"]


def test_b_zero_disables_length_normalisation():
    docs = {
        "short.txt": "ledger",
        "long.txt": "ledger " + "filler " * 200,
    }
    index = BM25Index.from_documents(docs, IndexConfig(path_weight=0, b=0.0))
    scores = {hit.path: hit.score for hit in index.search("ledger", k=5)}
    assert scores["short.txt"] == pytest.approx(scores["long.txt"])


def test_term_frequency_saturates():
    docs = {"one.txt": "term pad", "many.txt": ("term " * 100) + "pad"}
    index = BM25Index.from_documents(docs, IndexConfig(path_weight=0, b=0.0))
    scores = {hit.path: hit.score for hit in index.search("term", k=5)}
    ratio = scores["many.txt"] / scores["one.txt"]
    assert 1.0 < ratio < (1.2 + 1.0)  # bounded by (k1+1), never 100x


def test_idf_is_never_negative_even_for_a_universal_term():
    docs = {f"{i}.txt": "everywhere" for i in range(5)}
    index = BM25Index.from_documents(docs, IndexConfig(path_weight=0))
    assert index.idf("everywhere") >= 0.0
    assert index.idf("absent") > index.idf("everywhere")


def test_rare_terms_outrank_common_ones():
    docs = {f"common{i}.txt": "shared token" for i in range(9)}
    docs["rare.txt"] = "shared rare"
    index = BM25Index.from_documents(docs, IndexConfig(path_weight=0))
    hits = index.search("shared rare", k=3)
    assert hits[0].path == "rare.txt"


def test_ties_break_on_path_ascending_and_are_reproducible():
    docs = {"b.txt": "same body", "a.txt": "same body", "c.txt": "same body"}
    index = BM25Index.from_documents(docs, IndexConfig(path_weight=0))
    first = [hit.path for hit in index.search("same body", k=3)]
    second = [hit.path for hit in index.search("same body", k=3)]
    assert first == ["a.txt", "b.txt", "c.txt"] == second


def test_ranks_are_dense_and_one_based():
    hits = _tiny_index().search("budget ledger", k=10)
    assert [hit.rank for hit in hits] == list(range(1, len(hits) + 1))


def test_k_truncates_and_zero_k_returns_nothing():
    assert len(_tiny_index().search("ledger", k=2)) == 2
    assert _tiny_index().search("ledger", k=0) == []


def test_empty_query_and_empty_index_return_no_hits():
    assert _tiny_index().search("", k=5) == []
    assert _tiny_index().search("!!! ???", k=5) == []
    assert BM25Index.from_documents({}).search("anything", k=5) == []


def test_with_scoring_shares_the_corpus_and_only_changes_k1_b():
    """A scoring ablation must not silently rebuild a different corpus."""
    index = _tiny_index()
    view = index.with_scoring(b=0.0)
    assert view.paths is index.paths
    assert view.postings is index.postings
    assert view.doc_len is index.doc_len
    assert (view.config.b, index.config.b) == (0.0, 0.75)
    assert view.config.k1 == index.config.k1
    assert view.config.path_weight == index.config.path_weight
    # idf depends on document frequency alone, so the shared cache stays valid.
    assert view.idf("budget") == index.idf("budget")


def test_rank_of_reports_position_or_none():
    index = _tiny_index()
    assert index.rank_of("budget ledger", "a.txt") == 1
    assert index.rank_of("budget ledger", "d.txt") is None


# ------------------------------------------------------------- path weight


def test_path_weight_makes_the_filename_searchable():
    docs = {
        "budget_ledger.txt": "this body mentions nothing of interest",
        "other.txt": "this body mentions nothing of interest",
    }
    without = BM25Index.from_documents(docs, IndexConfig(path_weight=0))
    assert without.search("budget ledger", k=5) == []

    with_paths = BM25Index.from_documents(docs, IndexConfig(path_weight=3))
    hits = with_paths.search("budget ledger", k=5)
    assert [hit.path for hit in hits] == ["budget_ledger.txt"]


# ----------------------------------------------------------------- walking


def test_build_skips_unknown_extensions_binary_and_oversized_files(tmp_path):
    (tmp_path / "keep.py").write_text("budget ledger ceiling", encoding="utf-8")
    (tmp_path / "skip.bin").write_bytes(b"budget ledger")
    (tmp_path / "binary.py").write_bytes(b"budget\x00ledger")
    (tmp_path / "huge.md").write_text("budget " * 5000, encoding="utf-8")
    nested = tmp_path / "pkg" / "__pycache__"
    nested.mkdir(parents=True)
    (nested / "cached.py").write_text("budget ledger", encoding="utf-8")

    index = BM25Index.build(tmp_path, IndexConfig(max_file_bytes=1024))
    assert index.paths == ["keep.py"]
    report = index.report
    assert report.files_indexed == 1
    assert report.files_skipped_extension == 1
    assert report.files_skipped_binary == 1
    assert report.files_skipped_size == 1


def test_exclude_paths_keeps_a_file_out_of_the_corpus(tmp_path):
    """The evaluation's own query carriers must be excludable, and counted."""
    (tmp_path / "keep.py").write_text("ledger budget", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "carrier.py").write_text("ledger budget", encoding="utf-8")

    index = BM25Index.build(tmp_path, IndexConfig(exclude_paths=frozenset({"pkg/carrier.py"})))
    assert index.paths == ["keep.py"]
    assert index.report.files_skipped_excluded == 1
    assert [hit.path for hit in index.search("ledger", k=5)] == ["keep.py"]


def test_paths_are_repo_relative_posix(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("ledger", encoding="utf-8")
    index = BM25Index.build(tmp_path)
    assert index.paths == ["pkg/mod.py"]


def test_stats_report_raw_counters(tmp_path):
    (tmp_path / "a.py").write_text("ledger ledger budget", encoding="utf-8")
    index = BM25Index.build(tmp_path)
    stats = index.stats()
    assert stats["documents"] == 1
    assert stats["terms"] >= 2
    assert stats["tokens"] == sum(index.doc_len)
    assert stats["build"]["files_indexed"] == 1
    assert stats["build"]["build_seconds"] >= 0.0


# --------------------------------------------------------------------- CLI


def test_cli_emits_the_s09_json_contract(tmp_path, capsys):
    (tmp_path / "budget.py").write_text("a hard ceiling on money, ledger backed", encoding="utf-8")
    import bm25_index

    assert bm25_index.main(["--root", str(tmp_path), "--k", "3", "ledger ceiling"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == SCHEMA
    assert payload["read_only"] is True
    assert payload["results"][0]["query"] == "ledger ceiling"
    assert payload["results"][0]["hits"][0]["path"] == "budget.py"
    assert payload["results"][0]["hits"][0]["rank"] == 1


# ------------------------------------------------- known hits, real subtrees


@pytest.mark.parametrize(
    ("subtree", "query", "expected", "exclude"),
    [
        ("tools", "iron plan guard verify the plan digest", "iron_plan_guard.py", frozenset()),
        (
            "tools",
            "effect boundary entrypoint registry drift",
            "effect_boundary_check.py",
            frozenset(),
        ),
        (
            "experiments/forest_v2",
            "bm25 ranking baseline over repository files",
            "s07_bm25/bm25_index.py",
            FOREST_V2_QUERY_CARRIERS,
        ),
    ],
)
def test_known_hits_rank_first_in_a_real_subtree(subtree, query, expected, exclude):
    root = REPO_ROOT / subtree
    if not root.is_dir():  # pragma: no cover - worktree layout guard
        pytest.skip(f"{subtree} missing")
    index = BM25Index.build(root, IndexConfig(exclude_paths=exclude))
    hits = index.search(query, k=5)
    assert hits, f"no hits for {query!r}"
    assert hits[0].path == expected, [hit.path for hit in hits]


def test_confusable_neighbour_is_a_retained_known_miss():
    """RETAINED NEGATIVE RESULT -- do not "fix" by rewording the query.

    ``probe_call_resolution.py`` is the same-module baseline probe;
    ``probe_cross_module_resolution.py`` is its continuation and repeats every
    one of the query's terms while describing the baseline it extends.  Bag of
    words cannot separate "the document about X" from "the document that cites
    X"; the gold file lands at rank 3 (measured 2026-08-18).  This is precisely
    the class of failure a structure-aware retriever has to beat, so the miss
    is pinned rather than papered over.
    """
    root = REPO_ROOT / "experiments/forest_v2"
    if not root.is_dir():  # pragma: no cover - worktree layout guard
        pytest.skip("forest_v2 missing")
    index = BM25Index.build(root, IndexConfig(exclude_paths=FOREST_V2_QUERY_CARRIERS))
    rank = index.rank_of("same module call site resolution baseline probe", "probe_call_resolution.py")
    assert rank is not None and rank > 1, "the known miss disappeared -- re-measure and re-record"
    assert rank <= 5, f"the known miss got worse: rank {rank}"
