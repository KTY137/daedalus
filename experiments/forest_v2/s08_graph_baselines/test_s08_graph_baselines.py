"""EXPERIMENT s08 — tests.  Run directly:

    python -m pytest experiments/forest_v2/s08_graph_baselines/ -q

Every behavioural test builds a tiny synthetic tree in ``tmp_path``, so the
suite asserts mechanics, never this repository's measured numbers (those live
in the README and move whenever the tree moves).  Two structural tests do look
at the real slice: that it imports no repository package, and that it writes
nothing.
"""
from __future__ import annotations

import ast
import inspect
import string
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s08_api import (  # noqa: E402
    PLANES,
    Document,
    EvalResult,
    Hit,
    Query,
    evaluate,
    rank_of,
)
from s08_corpus import (  # noqa: E402
    Corpus,
    build_corpus,
    corpus_digest,
    cross_plane_edge_census,
    data_document_text,
    split_identifier,
    tokenize,
)
from s08_selftest import (  # noqa: E402
    CROSSTAB_PAIRS,
    KS,
    crosstab,
    crosstabs_by_cutoff,
    informative_queries,
    reachable_planes,
)
from s08_queries import (  # noqa: E402
    build_extended_queries,
    build_non_code_queries,
    build_queries,
    gold_plane_mix,
    leakage_note,
)
from s08_retrievers import (  # noqa: E402
    Bm25Index,
    CodeGraphRetriever,
    FourPlaneNoFusionRetriever,
    LexicalRetriever,
    SinglePlaneOracleRetriever,
    UnionNoFusionRetriever,
    _degree_preserving_rewire,
)

SLICE_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------- fixture


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> Path:
    """A four-plane miniature: three modules, one chain of imports, one orphan.

    ``alpha`` imports ``beta`` imports ``gamma``.  Only ``alpha`` mentions the
    word "harvest"; only ``gamma`` defines ``compute_signature``.  That lets a
    test show the graph reaching ``gamma`` from a query that only ``alpha``
    matches lexically.
    """
    root = tmp_path
    _write(
        root / "daedalus" / "alpha.py",
        '"""Harvest orchestration entry."""\n'
        "from daedalus.beta import beta_step\n\n\n"
        "def harvest_all(payload: dict) -> int:\n"
        '    """Harvest every payload row and return the count."""\n'
        "    return beta_step(payload)\n",
    )
    _write(
        root / "daedalus" / "beta.py",
        "from daedalus.gamma import compute_signature\n\n\n"
        "def beta_step(payload: dict) -> int:\n"
        "    return compute_signature(payload)\n",
    )
    _write(
        root / "daedalus" / "gamma.py",
        "def compute_signature(payload: dict) -> int:\n"
        '    """Return a stable integer signature for one payload."""\n'
        "    return len(payload)\n",
    )
    _write(root / "tools" / "orphan.py", "ORPHAN_MARKER = 1\n")
    _write(root / "daedalus" / "schema.json", '{"pipeline": {"stage_name": "value", "rows": [{"cell": 1}]}}')
    _write(root / "docs" / "guide.md", "The harvest pipeline calls `compute_signature` for every row.\n")
    return root


# ------------------------------------------------------------------ tokenising


def test_split_identifier_handles_snake_and_camel() -> None:
    assert split_identifier("load_env") == ["load", "env"]
    assert split_identifier("DeepSeekProvider") == ["deep", "seek", "provider"]
    assert split_identifier("HTTPServer") == ["http", "server"]


def test_tokenize_keeps_whole_identifier_and_parts() -> None:
    tokens = tokenize("compute_signature(payload)")
    assert "compute_signature" in tokens
    assert "compute" in tokens and "signature" in tokens


def test_tokenize_drops_stopwords_and_single_chars() -> None:
    assert tokenize("the a it x") == []


# ---------------------------------------------------------------------- corpus


def test_corpus_builds_all_four_planes(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    assert corpus.stats["docs_per_plane"]["code"] == 4
    assert corpus.stats["docs_per_plane"]["knowledge"] == 1
    assert corpus.stats["docs_per_plane"]["data"] == 1
    assert corpus.stats["docs_per_plane"]["type"] == 3  # orphan.py has no annotations
    assert "code:daedalus/alpha.py" in corpus.docs


def test_document_identity_is_plane_plus_locator() -> None:
    with pytest.raises(ValueError):
        Document(doc_id="wrong", plane="code", locator="a.py", text="x")
    with pytest.raises(ValueError):
        Document(doc_id="plasma:a.py", plane="plasma", locator="a.py", text="x")


def test_data_plane_indexes_keys_not_values(tiny_repo: Path) -> None:
    """A values-free Data plane is both plane-correct and secret-safe."""
    text = (tiny_repo / "daedalus" / "schema.json").read_text(encoding="utf-8")
    shaped = data_document_text(tiny_repo / "daedalus" / "schema.json", text)
    assert "stage_name" in shaped
    assert "value" not in shaped


def test_data_plane_never_carries_a_random_value(tmp_path: Path) -> None:
    """Generated at runtime on purpose: no secret-shaped literal lives in this file."""
    import random

    alphabet = string.ascii_letters + string.digits
    nonce = "".join(random.Random().choice(alphabet) for _ in range(40))
    path = tmp_path / "conf.json"
    path.write_text('{"token_field": "%s"}' % nonce, encoding="utf-8")
    shaped = data_document_text(path, path.read_text(encoding="utf-8"))
    assert "token_field" in shaped
    assert nonce not in shaped


def test_runs_json_receipts_are_excluded_from_the_data_plane(tiny_repo: Path) -> None:
    _write(tiny_repo / "runs" / "receipt.json", '{"receipt_id": 1}')
    corpus = build_corpus(tiny_repo)
    assert "data:runs/receipt.json" not in corpus.docs


# ----------------------------------------------------------------- code graph


def test_import_and_call_edges_are_built(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    assert ("daedalus.alpha", "daedalus.beta") in corpus.edges
    assert ("daedalus.beta", "daedalus.gamma") in corpus.edges
    # import edge (1.0) plus one resolved call site (0.5)
    assert corpus.edges[("daedalus.alpha", "daedalus.beta")] == pytest.approx(1.5)


def test_orphan_module_has_no_neighbours(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    assert corpus.neighbours("tools.orphan") == []


def test_graph_reaches_a_module_lexical_search_cannot(tiny_repo: Path) -> None:
    """The one thing a graph baseline must be able to do at all."""
    corpus = build_corpus(tiny_repo)
    lexical = LexicalRetriever.over("bm25", corpus.by_plane["code"])
    graph = CodeGraphRetriever(corpus, seeds=5)
    lexical_ids = {h.doc_id for h in lexical.query("harvest", k=10)}
    graph_ids = {h.doc_id for h in graph.query("harvest", k=10)}
    assert "code:daedalus/gamma.py" not in lexical_ids  # two hops away, no shared token
    assert "code:daedalus/gamma.py" in graph_ids
    hop = next(h for h in graph.query("harvest", k=10) if h.doc_id == "code:daedalus/gamma.py")
    assert hop.why.startswith("graph")


def test_graph_alpha_zero_equals_lexical_ranking(tiny_repo: Path) -> None:
    """alpha=0 must collapse onto the control, or the comparison is not clean."""
    corpus = build_corpus(tiny_repo)
    lexical = LexicalRetriever.over("bm25", corpus.by_plane["code"])
    graph = CodeGraphRetriever(corpus, alpha=0.0)
    assert [h.doc_id for h in graph.query("harvest payload", k=5)] == [
        h.doc_id for h in lexical.query("harvest payload", k=5)
    ]


def test_rewire_preserves_unweighted_degree(tiny_repo: Path) -> None:
    _write(tiny_repo / "daedalus" / "delta.py", "from daedalus.alpha import harvest_all\n")
    _write(tiny_repo / "daedalus" / "epsilon.py", "from daedalus.gamma import compute_signature\n")
    corpus = build_corpus(tiny_repo)
    rewired = _degree_preserving_rewire(corpus, seed=1)
    original = corpus.adjacency()
    assert sum(len(v) for v in rewired.values()) == sum(len(v) for v in original.values())
    for module in original:
        assert len(rewired.get(module, [])) == len(original[module])


def test_graph_retriever_is_code_plane_only(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    graph = CodeGraphRetriever(corpus)
    assert {h.plane for h in graph.query("harvest signature payload", k=10)} == {"code"}


# ------------------------------------------------------------------ retrievers


def test_bm25_ranks_the_defining_module_first(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    index = Bm25Index(corpus.by_plane["code"])
    top = index.search("compute signature stable integer", k=1)
    assert top and top[0][0].doc_id == "code:daedalus/gamma.py"


def test_bm25_is_deterministic_on_ties(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    index = Bm25Index(corpus.by_plane["code"])
    assert [d.doc_id for d, _ in index.search("payload", 5)] == [
        d.doc_id for d, _ in index.search("payload", 5)
    ]


def test_no_fusion_round_robins_across_planes(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    no_fusion = FourPlaneNoFusionRetriever(corpus)
    hits = no_fusion.query("harvest signature stage_name", k=4)
    planes = [h.plane for h in hits]
    first_seen = list(dict.fromkeys(planes))
    # the cycle visits the planes in the declared order; a plane with no hit at
    # this depth is skipped, never reordered
    assert first_seen == [p for p in no_fusion.order if p in first_seen]
    assert len(first_seen) > 1  # more than one index contributed


def test_no_fusion_never_compares_scores_across_planes(tiny_repo: Path) -> None:
    """The ordering must come from the plane cycle, not from the score column."""
    corpus = build_corpus(tiny_repo)
    hits = FourPlaneNoFusionRetriever(corpus).query("harvest signature payload", k=8)
    scores = [h.score for h in hits]
    assert scores != sorted(scores, reverse=True) or len({h.plane for h in hits}) == 1


def test_per_plane_query_returns_only_that_plane(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    no_fusion = FourPlaneNoFusionRetriever(corpus)
    for plane in ("code", "type", "data", "knowledge"):
        assert all(h.plane == plane for h in no_fusion.query_plane(plane, "harvest", k=5))


def test_oracle_is_at_least_as_good_as_any_single_plane(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    no_fusion = FourPlaneNoFusionRetriever(corpus)
    oracle = SinglePlaneOracleRetriever(no_fusion)
    gold = "code:daedalus/gamma.py"
    oracle.set_gold(gold)
    oracle_rank = rank_of(oracle.query("stable integer signature", k=10), gold)
    for plane in no_fusion.order:
        plane_rank = rank_of(no_fusion.query_plane(plane, "stable integer signature", k=10), gold)
        assert plane_rank == 0 or oracle_rank <= plane_rank


# ------------------------------------------------ no-fusion: slot allocation
#
# These four encode the two defects an adversarial review found in the landed
# slice.  They are written so that reverting the fix turns them red.


def _starvation_corpus() -> "Corpus":
    """Six code documents ranked 1..6 for "widget", three docs in every other plane.

    Same length everywhere, decreasing term frequency, so the code index's
    ranking is deterministic and the gold sits at code-rank 4 — outside the
    three slots a four-way round-robin can spend on the code plane within a
    cutoff of ten.
    """
    corpus = Corpus(root=Path("."))
    for i in range(1, 7):
        text = " ".join(["widget"] * (7 - i) + [f"pad{i}x{j}" for j in range(i - 1 + 4)])
        corpus.add(
            Document(
                doc_id=f"code:c{i}.py",
                plane="code",
                locator=f"c{i}.py",
                text=text,
                tokens=tuple(tokenize(text)),
            )
        )
    for plane, suffix in (("type", "pyi"), ("data", "json"), ("knowledge", "md")):
        for j in range(1, 4):
            text = "widget " * 3
            corpus.add(
                Document(
                    doc_id=f"{plane}:{plane}{j}.{suffix}",
                    plane=plane,
                    locator=f"{plane}{j}.{suffix}",
                    text=text,
                    tokens=tuple(tokenize(text)),
                )
            )
    return corpus


def test_round_robin_starves_the_only_answer_bearing_plane() -> None:
    """CRITICAL 1: a shared budget split four ways is not "no fusion", it is a handicap.

    The gold is the code index's 4th hit.  A four-way round-robin inside a
    cutoff of ten reaches only the code index's top-3, so it misses a document
    that the very same index ranks 4th.  The union arm, given each plane its
    own top-k, finds it at exactly its code-index rank.
    """
    corpus = _starvation_corpus()
    gold = "code:c4.py"
    code_only = LexicalRetriever.over("code_only", corpus.by_plane["code"])
    code_rank = rank_of(code_only.query("widget", k=10), gold)
    assert code_rank == 4, f"fixture drifted: expected code-rank 4, got {code_rank}"

    round_robin = FourPlaneNoFusionRetriever(corpus)
    union = UnionNoFusionRetriever(corpus)
    assert rank_of(round_robin.query("widget", k=10), gold) == 0  # starved out
    assert rank_of(union.query("widget", k=10), gold) == code_rank  # not starved


def test_union_no_fusion_gives_every_plane_its_own_top_k() -> None:
    corpus = _starvation_corpus()
    union = UnionNoFusionRetriever(corpus)
    hits = union.query("widget", k=3)
    assert [h.plane for h in hits] == ["code"] * 3 + ["type"] * 3 + ["data"] * 3 + ["knowledge"] * 3
    code_only = LexicalRetriever.over("code_only", corpus.by_plane["code"])
    assert [h.doc_id for h in hits[:3]] == [h.doc_id for h in code_only.query("widget", k=3)]


def test_union_no_fusion_never_compares_scores_across_planes() -> None:
    """A later plane outscoring the first must NOT be able to jump the queue."""
    corpus = _starvation_corpus()
    union = UnionNoFusionRetriever(corpus)
    hits = union.query("widget", k=6)
    best_code = max(h.score for h in hits if h.plane == "code")
    best_other = max(h.score for h in hits if h.plane != "code")
    assert best_other > best_code, "fixture drifted: no cross-plane score inversion to defend against"
    assert hits[0].plane == "code", "the concatenation order decided rank, not the score column"


def test_union_no_fusion_plane_order_decides_rank() -> None:
    """The order is a declared prior over planes, and it is worth everything here."""
    corpus = _starvation_corpus()
    gold = "code:c1.py"
    code_first = UnionNoFusionRetriever(corpus, order=("code", "type", "data", "knowledge"))
    code_last = UnionNoFusionRetriever(corpus, order=("type", "data", "knowledge", "code"))
    assert rank_of(code_first.query("widget", k=10), gold) == 1
    # code-last pushes the code block down by exactly the number of documents the
    # other three planes returned first (3 + 3 + 3 here, not 3 x k: the fixture's
    # non-code planes hold fewer than k documents).
    hits_last = code_last.query("widget", k=10)
    preceding = sum(1 for h in hits_last if h.plane != "code")
    assert preceding == 9
    assert rank_of(hits_last, gold) == preceding + 1 == 10


def test_every_retriever_answers_the_shared_query_call(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    retrievers = [
        LexicalRetriever.over("bm25_code_only", corpus.by_plane["code"]),
        CodeGraphRetriever(corpus),
        FourPlaneNoFusionRetriever(corpus),
    ]
    for retriever in retrievers:
        hits = retriever.query("harvest", k=3)
        assert isinstance(retriever.name, str) and retriever.name
        assert len(hits) <= 3
        for hit in hits:
            assert isinstance(hit, Hit)
            assert hit.doc_id == f"{hit.plane}:{hit.locator}"


def test_empty_query_returns_no_hits(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    for retriever in (
        LexicalRetriever.over("bm25", corpus.by_plane["code"]),
        CodeGraphRetriever(corpus),
        FourPlaneNoFusionRetriever(corpus),
    ):
        assert retriever.query("", k=5) == []


# --------------------------------------------------------------------- metrics


def test_rank_of_is_one_based_and_zero_when_absent() -> None:
    hits = [Hit("code:a.py", 1.0, "code", "a.py"), Hit("code:b.py", 0.5, "code", "b.py")]
    assert rank_of(hits, "code:a.py") == 1
    assert rank_of(hits, "code:b.py") == 2
    assert rank_of(hits, "code:c.py") == 0


def test_evaluate_counts_raw_hits_and_mrr() -> None:
    class Fake:
        name = "fake"

        def query(self, text: str, k: int = 10) -> list[Hit]:
            order = {"first": 1, "third": 3, "missing": 0}[text]
            hits = [Hit(f"code:{i}.py", 1.0 / i, "code", f"{i}.py") for i in range(1, 6)]
            return hits if order else []

    queries = [
        Query("q1", "f", "first", "code:1.py"),
        Query("q2", "f", "third", "code:3.py"),
        Query("q3", "f", "missing", "code:9.py"),
    ]
    result = evaluate(Fake(), queries, ks=(1, 5), family="f")
    assert result.hits_at[1] == 1
    assert result.hits_at[5] == 2
    assert result.empty_results == 1
    assert result.mrr == pytest.approx((1.0 + 1 / 3) / 3)


def test_eval_result_reports_zero_on_an_empty_query_set() -> None:
    empty = EvalResult(retriever="r", family="f", n_queries=0)
    assert empty.recall_at(1) == 0.0 and empty.mrr == 0.0


# --------------------------------------------------------------------- queries


def test_query_families_are_derived_and_gold_is_a_code_document(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    queries = build_queries(corpus, max_per_family=10)
    families = {q.family for q in queries}
    assert "symbol" in families and "docstring" in families
    assert all(q.gold_doc_id.startswith("code:") for q in queries)


def test_docstring_query_has_the_symbol_name_removed(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    docstring_queries = [q for q in build_queries(corpus, 10) if q.family == "docstring"]
    assert docstring_queries
    for query in docstring_queries:
        symbol = query.qid.rsplit(":", 1)[-1]
        for part in split_identifier(symbol):
            assert part not in query.text.split()


def test_knowledge_ref_query_comes_from_markdown_and_points_at_code(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    refs = [q for q in build_queries(corpus, 10) if q.family == "knowledge_ref"]
    assert refs, "the guide mentions `compute_signature` in backticks"
    assert refs[0].gold_doc_id == "code:daedalus/gamma.py"
    assert "compute_signature" not in refs[0].text


def test_query_set_is_reproducible(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    first = [(q.qid, q.text) for q in build_queries(corpus, 10)]
    second = [(q.qid, q.text) for q in build_queries(build_corpus(tiny_repo), 10)]
    assert first == second


def test_leakage_note_reports_overlap_per_family(tiny_repo: Path) -> None:
    corpus = build_corpus(tiny_repo)
    note = leakage_note(corpus, build_queries(corpus, 10))
    assert note
    for family, values in note.items():
        assert 0.0 <= values["mean_query_token_overlap_with_gold"] <= 1.0


# ------------------------------------------------ queries: non-code gold labels


@pytest.fixture()
def cross_plane_repo(tmp_path: Path) -> Path:
    """A tree where one Markdown file names another Markdown file and a schema file."""
    root = tmp_path
    _write(root / "daedalus" / "alpha.py", "def harvest_all(payload: dict) -> int:\n    return 1\n")
    _write(root / "daedalus" / "settings.json", '{"telemetry": {"sample_rate": 1}}')
    _write(
        root / "docs" / "index.md",
        "The retention rules for every campaign live in docs/policy.md and nowhere else.\n"
        "Sampling behaviour is configured by daedalus/settings.json at startup.\n",
    )
    _write(root / "docs" / "policy.md", "Retention rules for campaign artifacts.\n")
    return root


def test_non_code_families_put_the_gold_outside_the_code_plane(cross_plane_repo: Path) -> None:
    """CRITICAL 2 follow-on: with only code gold labels the routing question is undecidable."""
    corpus = build_corpus(cross_plane_repo)
    queries = build_non_code_queries(corpus)
    families = {q.family for q in queries}
    assert families == {"doc_ref", "data_ref"}
    assert {q.gold_doc_id for q in queries} == {"knowledge:docs/policy.md", "data:daedalus/settings.json"}
    assert all(not q.gold_doc_id.startswith("code:") for q in queries)


def test_non_code_query_strips_the_named_path(cross_plane_repo: Path) -> None:
    """The give-away path must not survive in the query text."""
    corpus = build_corpus(cross_plane_repo)
    for query in build_non_code_queries(corpus):
        tokens = set(tokenize(query.text))
        assert "policy" not in tokens or query.family != "doc_ref"
        assert "settings" not in tokens or query.family != "data_ref"


def test_frozen_query_set_still_has_only_code_gold(tiny_repo: Path) -> None:
    """``build_queries`` is frozen: the correction ADDS families, it does not edit these."""
    corpus = build_corpus(tiny_repo)
    queries = build_queries(corpus)
    assert {q.family for q in queries} <= {"symbol", "docstring", "knowledge_ref"}
    assert gold_plane_mix(queries).keys() <= {"code"}


def test_extended_set_is_the_frozen_set_plus_the_additions(cross_plane_repo: Path) -> None:
    corpus = build_corpus(cross_plane_repo)
    frozen = build_queries(corpus)
    extended = build_extended_queries(corpus)
    assert extended[: len(frozen)] == frozen
    assert len(extended) == len(frozen) + len(build_non_code_queries(corpus))


def test_no_gold_document_dominates_a_non_code_family(tmp_path: Path) -> None:
    """Six sources all point at one document; the cap must keep it to four."""
    from collections import Counter

    for i in range(6):
        _write(
            tmp_path / "docs" / f"source{i}.md",
            f"Chapter {i} defers the retention question entirely to docs/policy.md instead.\n",
        )
    _write(tmp_path / "docs" / "policy.md", "Retention rules for campaign artifacts.\n")
    counts = Counter(q.gold_doc_id for q in build_non_code_queries(build_corpus(tmp_path)))
    assert counts["knowledge:docs/policy.md"] == 4, "the per-gold cap did not bind"


def test_non_code_queries_are_deterministic(cross_plane_repo: Path) -> None:
    corpus = build_corpus(cross_plane_repo)
    first = [q.qid for q in build_non_code_queries(corpus)]
    second = [q.qid for q in build_non_code_queries(build_corpus(cross_plane_repo))]
    assert first == second


# ------------------------------------------------------- slice-level structure


def test_slice_imports_no_repository_package() -> None:
    """Isolation runs both ways; this half is mechanically checkable here."""
    forbidden = {"daedalus", "tools", "runs", "scripts"}
    for path in sorted(SLICE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert not (set(names) & forbidden), f"{path.name} imports repository code: {names}"


def test_crosstabs_are_reported_at_every_cutoff() -> None:
    """A single-cutoff crosstab hid a sign flip; it must not become emittable again.

    Against the degree-preserving rewired control the real graph is -63 at k=1,
    -7 at k=5 and +6 at k=10.  Reporting only k=10 understates kill criterion
    14.2 by an order of magnitude, in the direction that favours the hypothesis.

    This asserts on the EMITTED BLOCK, not on the source text.  The first
    version of this check read the source and looked for any dict comprehension
    over ``KS``; a mutation that kept the honest key name and pinned the loop to
    ``(10,)`` passed it, because other comprehensions over ``KS`` exist in the
    module.  A guard that a mutation walks through is not a guard.
    """
    ranks = {
        "bm25_code_only": [1, 2, 3],
        "graph_code_only": [3, 1, 2],
        "graph_rewired": [2, 3, 1],
        "four_plane_no_fusion": [1, 1, 9],
        "union_no_fusion": [4, 5, 6],
        "bm25_single_index_all_planes": [7, 8, 9],
    }
    block = crosstabs_by_cutoff(ranks)
    assert set(block["cutoffs"]) == {str(k) for k in KS}, "a cutoff went missing from the report"
    for k, row in block["cutoffs"].items():
        assert set(row) == {name for name, _, _ in CROSSTAB_PAIRS}, f"pairs missing at k={k}"
        for name, entry in row.items():
            assert entry["net_b_minus_a"] == entry["only_b"] - entry["only_a"]
            assert entry["discordant"] == entry["only_a"] + entry["only_b"]


def test_crosstab_builder_takes_no_cutoff_argument() -> None:
    """The pin has to be impossible at the call site too, not only inside."""
    params = list(inspect.signature(crosstabs_by_cutoff).parameters)
    assert params == ["ranks"], f"a cutoff argument would let a caller pin it: {params}"


def test_reported_cutoffs_are_the_frozen_three() -> None:
    """``crosstabs_by_cutoff`` reads module ``KS``; narrowing KS must not be quiet."""
    assert KS == (1, 5, 10)


def test_crosstab_sign_can_flip_between_cutoffs() -> None:
    """Why the checks above exist, as mechanics rather than as a comment."""
    # B wins at k=2 (rank 2 vs 3) but loses at k=1 (rank 3 vs 1) on the other query
    a_ranks, b_ranks = [1, 3], [3, 2]
    assert crosstab(a_ranks, b_ranks, 1)["only_a"] == 1
    assert crosstab(a_ranks, b_ranks, 1)["only_b"] == 0
    assert crosstab(a_ranks, b_ranks, 2)["only_a"] == 1
    assert crosstab(a_ranks, b_ranks, 2)["only_b"] == 1


def test_corpus_digest_is_stable_and_content_sensitive(cross_plane_repo: Path) -> None:
    """A number without a corpus digest names no corpus."""
    first = corpus_digest(build_corpus(cross_plane_repo))
    assert len(first) == 64
    assert first == corpus_digest(build_corpus(cross_plane_repo)), "digest is not stable"
    target = sorted(cross_plane_repo.rglob("*.md"))[0]
    target.write_text(target.read_text(encoding="utf-8") + "\nan added line\n", encoding="utf-8")
    assert corpus_digest(build_corpus(cross_plane_repo)) != first, "digest ignored a change"


def test_cross_plane_edge_census_counts_a_real_cross_plane_edge(tiny_repo: Path) -> None:
    """The census must be able to report a cross-plane edge, or its 0 means nothing.

    Kill criterion 14.2 speaks of degree-preserving randomized CROSS-PLANE
    edges.  This slice's graph reports 0 of them.  That reading is only worth
    anything if the census would have counted one had it existed -- so one is
    injected here and must be seen.
    """
    corpus = build_corpus(tiny_repo)
    before = cross_plane_edge_census(corpus)
    assert before["total_edges"] > 0, "fixture produced no edges to census"
    assert before["cross_plane_edges"] == 0
    assert set(before["endpoint_plane_counts"]) == {"code"}

    knowledge_doc = sorted(d.doc_id for d in corpus.by_plane["knowledge"])[0]
    code_module = sorted(corpus.doc_id_by_module)[0]
    corpus.doc_id_by_module["__synthetic_knowledge_node__"] = knowledge_doc
    corpus.edges[(code_module, "__synthetic_knowledge_node__")] = 1.0

    after = cross_plane_edge_census(corpus)
    assert after["cross_plane_edges"] == 1, "the census cannot see a cross-plane edge"
    assert after["endpoint_plane_counts"].get("knowledge") == 1
    assert after["total_edges"] == before["total_edges"] + 1


def test_reachable_planes_names_what_an_arm_can_return(cross_plane_repo: Path) -> None:
    """An arm that cannot return the gold plane cannot be refuted on it.

    Both graph arms index the code plane only, so on a non-code-gold query they
    and their control both score 0 and agree by construction.  This is the
    measurement behind that statement.
    """
    corpus = build_corpus(cross_plane_repo)
    queries = build_non_code_queries(corpus)
    assert queries, "fixture produced no non-code queries"

    code_only = LexicalRetriever.over("bm25_code_only", corpus.by_plane["code"])
    all_planes = LexicalRetriever.over(
        "bm25_single_index_all_planes",
        [d for plane in PLANES for d in corpus.by_plane.get(plane, [])],
    )
    graph = CodeGraphRetriever(corpus)

    assert reachable_planes(code_only, queries, 10)["can_return_non_code"] is False
    assert reachable_planes(graph, queries, 10)["can_return_non_code"] is False
    assert reachable_planes(all_planes, queries, 10)["can_return_non_code"] is True


def test_padding_with_unanswerable_queries_adds_no_information() -> None:
    """Why an equivalence test can be walked to KILL without new evidence.

    Two arms that both miss a query agree on it.  Adding such queries grows n
    and leaves the discordant count untouched, so the difference of proportions
    and its interval both shrink towards zero -- towards EQUIVALENT -- on no new
    observation at all.  That is exactly what the 138 non-code queries do to the
    graph-vs-rewiring comparison, whose arms are both code-only.
    """
    # 0 = not retrieved.  q1 only A, q2 only B, q3 both, q4 neither.
    a_real, b_real = [1, 0, 3, 0], [0, 2, 3, 0]
    informative_real = informative_queries(a_real, b_real)
    padding = [0] * 50  # both arms miss every padded query, exactly like the 138
    informative_padded = informative_queries(a_real + padding, b_real + padding)
    assert informative_real == informative_padded, "padding changed the evidence, not just n"
    assert informative_padded["10"] > 0

    for k in (1, 5, 10):
        counts_real = crosstab(a_real, b_real, k)
        counts_padded = crosstab(a_real + padding, b_real + padding, k)
        assert counts_padded["neither"] == counts_real["neither"] + len(padding)
        diff_real = (counts_real["only_b"] - counts_real["only_a"]) / len(a_real)
        diff_padded = (counts_padded["only_b"] - counts_padded["only_a"]) / (
            len(a_real) + len(padding)
        )
        assert abs(diff_padded) <= abs(diff_real), "padding failed to shrink the difference"


def test_no_arm_is_called_fusion_unless_a_fusion_retriever_exists() -> None:
    """An earlier retraction in this slice was about exactly this word.

    Nothing here fuses evidence across planes: the no-fusion arms concatenate,
    and the joint index is one index over all documents.  Naming any of them a
    fusion arm would restate the missing second arm of criterion 14.3 as if it
    were present.
    """
    for path in sorted(SLICE_DIR.glob("s08_*.py")):
        source = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), 1):
            lowered = line.lower()
            if "fusion" not in lowered:
                continue
            residual = lowered.replace("no_fusion", "").replace("no-fusion", "")
            residual = residual.replace("nofusion", "").replace("nofusionretriever", "")
            if "fusion" not in residual:
                continue
            assert not residual.strip().startswith(("class ", "def ")), (
                f"{path.name}:{lineno} declares a fusion arm: {line.strip()}"
            )
            assert "name=" not in residual, (
                f"{path.name}:{lineno} names an arm fusion: {line.strip()}"
            )


def test_slice_contains_no_write_or_subprocess_call() -> None:
    """A read-only experiment that opens a file for writing is not read-only."""
    banned = {"write_text", "write_bytes", "mkdir", "remove", "unlink", "rmtree", "system", "Popen", "run"}
    for path in sorted(SLICE_DIR.glob("s08_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned, f"{path.name} calls {node.func.attr}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
                assert mode is None, f"{path.name} opens a file with an explicit mode"
