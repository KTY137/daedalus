"""EXPERIMENT s08 — RAW self-test.  One JSON object on stdout, nothing written.

    python experiments/forest_v2/s08_graph_baselines/s08_selftest.py [repo_root]

What it prints, in this order: the corpus it actually built (so the numbers can
be re-derived), the query set with its leakage note, then every retriever's RAW
hit counts per query family.  Fractions are printed alongside the counts, never
instead of them.

The comparison is budget-equal by construction: identical query set, identical
cutoffs, identical tokeniser, single process, no model calls, no spend.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s08_api import PLANES, evaluate, rank_of  # noqa: E402
from s08_corpus import build_corpus  # noqa: E402
from s08_queries import (  # noqa: E402
    build_non_code_queries,
    build_queries,
    by_family,
    gold_plane_mix,
    leakage_note,
)
from s08_retrievers import (  # noqa: E402
    CodeGraphRetriever,
    FourPlaneNoFusionRetriever,
    LexicalRetriever,
    SinglePlaneOracleRetriever,
    UnionNoFusionRetriever,
)

KS = (1, 5, 10)
STARVATION_KS = (1, 2, 3, 4, 5, 10)
SENSITIVITY_ALPHAS = (0.0, 0.25, 0.5, 0.75)


def rank_vector(retriever, queries, kmax: int) -> list[int]:
    """1-based rank of each query's gold document, 0 when it is not in the top-kmax."""
    return [rank_of(retriever.query(q.text, k=kmax), q.gold_doc_id) for q in queries]


def crosstab(a_ranks: list[int], b_ranks: list[int], k: int) -> dict[str, int]:
    """RAW rescue/loss counts between two retrievers at one cutoff.

    A net difference of +6 can be +6/-0 or +40/-34; those are different systems
    and the aggregate hides which one you have.
    """
    both = only_a = only_b = neither = 0
    for ra, rb in zip(a_ranks, b_ranks):
        ha, hb = 1 <= ra <= k, 1 <= rb <= k
        both += ha and hb
        only_a += ha and not hb
        only_b += hb and not ha
        neither += not ha and not hb
    return {"both": both, "only_a": only_a, "only_b": only_b, "neither": neither, "k": k}


def _repo_root(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1]).resolve()
    return Path(__file__).resolve().parents[3]


def _oracle_eval(oracle: SinglePlaneOracleRetriever, queries, ks=KS) -> dict:
    """The oracle needs the gold per query, so it cannot use the plain loop."""
    hits = {k: 0 for k in ks}
    rr = 0.0
    started = time.perf_counter()
    for query in queries:
        oracle.set_gold(query.gold_doc_id)
        result = oracle.query(query.text, k=max(ks))
        rank = rank_of(result, query.gold_doc_id)
        if rank:
            rr += 1.0 / rank
            for k in ks:
                if rank <= k:
                    hits[k] += 1
    n = len(queries)
    return {
        "retriever": oracle.name,
        "n_queries": n,
        "hits_at": {str(k): hits[k] for k in ks},
        "recall_at": {str(k): round(hits[k] / n, 4) if n else 0.0 for k in ks},
        "mrr": round(rr / n, 4) if n else 0.0,
        "seconds": round(time.perf_counter() - started, 3),
        "note": "UPPER BOUND ONLY - reads the gold label to pick a plane; not a system",
    }


def main(argv: list[str]) -> int:
    root = _repo_root(argv)
    report: dict[str, object] = {
        "experiment": "forest_v2/s08_graph_baselines",
        "classification": "EXPERIMENT",
        "repo_root": str(root),
        "measurement": "RAW",
    }

    t0 = time.perf_counter()
    corpus = build_corpus(root)
    build_seconds = time.perf_counter() - t0
    report["corpus"] = {**corpus.stats, "build_seconds": round(build_seconds, 3)}

    queries = build_queries(corpus)
    families = by_family(queries)
    # The frozen 600 stay exactly as they were; the non-code-gold families are an
    # addition, built with their own generator so the frozen stream is untouched.
    non_code = build_non_code_queries(corpus)
    non_code_families = by_family(non_code)
    extended = queries + non_code
    report["queries"] = {
        "total": len(queries),
        "per_family": {f: len(q) for f, q in sorted(families.items())},
        "seed": 20260818,
        "leakage_note": leakage_note(corpus, queries),
    }

    t1 = time.perf_counter()
    code_docs = corpus.by_plane.get("code", [])
    all_docs = [d for plane in PLANES for d in corpus.by_plane.get(plane, [])]
    bm25_code = LexicalRetriever.over("bm25_code_only", code_docs)
    bm25_all = LexicalRetriever.over("bm25_single_index_all_planes", all_docs)
    graph = CodeGraphRetriever(corpus)
    graph_rewired = CodeGraphRetriever(corpus, rewire=True)
    no_fusion = FourPlaneNoFusionRetriever(corpus)
    union = UnionNoFusionRetriever(corpus)
    union_truncated = UnionNoFusionRetriever(corpus, truncate=True)
    union_code_last = UnionNoFusionRetriever(corpus, order=("type", "data", "knowledge", "code"))
    oracle = SinglePlaneOracleRetriever(no_fusion)
    index_seconds = time.perf_counter() - t1
    report["index_build_seconds"] = round(index_seconds, 3)
    report["graph"] = {
        "modules": len(corpus.modules),
        "edges": len(corpus.edges),
        "isolated_modules": sum(1 for m in corpus.modules if not corpus.neighbours(m)),
        "mean_degree": round(2 * len(corpus.edges) / len(corpus.modules), 3) if corpus.modules else 0.0,
        "params": {"alpha": graph.alpha, "hops": graph.hops, "seeds": graph.seeds},
    }

    retrievers = [
        bm25_code,
        graph,
        graph_rewired,
        no_fusion,
        union,
        union_truncated,
        union_code_last,
        bm25_all,
    ]
    results: list[dict] = []
    for retriever in retrievers:
        for family, family_queries in sorted(families.items()):
            results.append(evaluate(retriever, family_queries, KS, family=family).as_dict(KS))
        results.append(evaluate(retriever, queries, KS, family="all").as_dict(KS))
    report["results"] = results

    report["oracle_upper_bound"] = {
        family: _oracle_eval(oracle, family_queries) for family, family_queries in sorted(families.items())
    }

    # Per-plane recall of the no-fusion baseline: which single index would have
    # answered?  Gold is always a code document, so this shows the routing cost.
    plane_recall: dict[str, dict[str, dict[str, float | int]]] = {}
    for family, family_queries in sorted(families.items()):
        per_plane: dict[str, dict[str, float | int]] = {}
        for plane in PLANES:
            hit = 0
            for query in family_queries:
                hits = no_fusion.query_plane(plane, query.text, max(KS))
                if rank_of(hits, query.gold_doc_id):
                    hit += 1
            per_plane[plane] = {
                "hits_at_10": hit,
                "recall_at_10": round(hit / len(family_queries), 4) if family_queries else 0.0,
            }
        plane_recall[family] = per_plane
    report["no_fusion_per_plane_recall_at_10"] = plane_recall

    # --- CORRECTION 1: the round-robin arm was starved, and this measures it.
    # Round-robin over four planes hands the code index slots 1, 5, 9 out of
    # ten.  Because every gold label here is a code document, that arm can
    # never do better than the code index's own top-3.  Both sides of that
    # identity are printed so the claim is checkable and not merely asserted.
    code_by_k = evaluate(bm25_code, queries, STARVATION_KS, family="all").as_dict(STARVATION_KS)
    rr_ranks = rank_vector(no_fusion, queries, kmax=max(KS))
    union_ranks_all = rank_vector(union, queries, kmax=max(KS))
    code_ranks_all = rank_vector(bm25_code, queries, kmax=max(KS))
    report["round_robin_starvation"] = {
        "claim": "four_plane_no_fusion@10 is bounded by bm25_code_only@3, because "
                 "round-robin gives the only answer-bearing plane 3 of 10 slots",
        "bm25_code_only_hits_by_cutoff": code_by_k["hits_at"],
        "four_plane_no_fusion_hits_at_10": sum(1 for r in rr_ranks if 1 <= r <= max(KS)),
        "union_no_fusion_hits_at_10": sum(1 for r in union_ranks_all if 1 <= r <= max(KS)),
        "bm25_code_only_hits_at_10": sum(1 for r in code_ranks_all if 1 <= r <= max(KS)),
        "union_rank_equals_code_rank_for_n_queries": sum(
            1 for u, c in zip(union_ranks_all, code_ranks_all) if u == c
        ),
        "union_rank_differs_for_n_queries": sum(
            1 for u, c in zip(union_ranks_all, code_ranks_all) if u != c
        ),
        "note": "the union arm reads 4k documents to answer a cutoff-k question; "
                "R@k is unaffected, MRR over the full list is generous to it "
                "(see the ',truncated' row for the clipped comparison)",
    }

    # --- CORRECTION 2: hypothesis (b) is re-reported against the comparator the
    # frozen sub-spec NAMES ("one index over the same documents" =
    # bm25_single_index_all_planes), not against the code-only subset index.
    def _hits(ranks: list[int]) -> dict[str, int]:
        return {str(k): sum(1 for r in ranks if 1 <= r <= k) for k in KS}

    def _named_comparison(query_list) -> dict:
        """Re-report (b) on one query set against the comparator the spec names."""
        single = rank_vector(bm25_all, query_list, kmax=max(KS))
        block: dict[str, object] = {
            "n_queries": len(query_list),
            "arms": {"bm25_single_index_all_planes": _hits(single)},
        }
        for arm_name, arm in (("four_plane_no_fusion", no_fusion), ("union_no_fusion", union)):
            arm_ranks = rank_vector(arm, query_list, kmax=max(KS))
            block["arms"][arm_name] = _hits(arm_ranks)  # type: ignore[index]
            deltas = {k: _hits(arm_ranks)[k] - _hits(single)[k] for k in _hits(single)}
            signs = {1 if v > 0 else (-1 if v < 0 else 0) for v in deltas.values()}
            consistent = len(signs - {0}) == 1 and 0 not in signs
            # 5 percentage points OF THIS QUERY SET, not a fixed hit count: a
            # constant threshold would silently call a 12 pp gap on 138 queries
            # a null, which is the same under-reporting this fix exists to undo.
            threshold = 0.05 * len(query_list)
            material = abs(deltas["10"]) >= threshold and consistent
            if material and deltas["10"] < 0:
                verdict = "CONFIRMED (materially less, as the spec claims)"
            elif material:
                verdict = "REFUTED (material, but the OPPOSITE direction to the spec claim)"
            else:
                verdict = "NULL (no material difference in either direction)"
            block[f"{arm_name}_vs_named_comparator"] = {
                "delta_hits": deltas,
                "same_sign_across_cutoffs": consistent,
                "verdict": verdict,
            }
        return block

    report["hypothesis_b_vs_named_comparator"] = {
        "spec_text": "four independent BM25 indices with no cross-plane scoring reach "
                     "materially less than one index over the same documents",
        "named_comparator": "bm25_single_index_all_planes",
        "comparator_used_in_the_landed_report": "bm25_code_only (NOT the named one)",
        "materiality_rule": "declared in THIS correction, not at freeze time: material = "
                            "|delta hits@10| >= 5% of the query set AND the same sign at "
                            "k=1, 5 and 10",
        "direction_rule": "the spec claim is DIRECTIONAL ('reach materially less'), so "
                          "delta = no_fusion - single_index: materially negative CONFIRMS, "
                          "materially positive REFUTES, anything else is a NULL",
        "on_frozen_600": _named_comparison(queries),
        "on_extended_set": _named_comparison(extended),
        "on_non_code_gold_only": _named_comparison(non_code),
    }

    # --- CORRECTION 3: gold labels outside the code plane, so that plane routing
    # has something to get right.  The frozen 600 are untouched; this is an
    # addition reported beside them.
    ext_arms = [bm25_code, no_fusion, union, union_code_last, bm25_all, graph]
    ext_results: list[dict] = []
    for retriever in ext_arms:
        for family, family_queries in sorted(non_code_families.items()):
            ext_results.append(evaluate(retriever, family_queries, KS, family=family).as_dict(KS))
        ext_results.append(evaluate(retriever, non_code, KS, family="non_code_only").as_dict(KS))
        ext_results.append(evaluate(retriever, extended, KS, family="extended_all").as_dict(KS))
    report["extended_query_set"] = {
        "purpose": "the frozen 600 have a code gold label for every query, which makes any "
                   "cross-plane method structurally unable to win; these families put the "
                   "answer in the knowledge and data planes instead",
        "frozen_set": {"n": len(queries), "gold_plane_mix": gold_plane_mix(queries)},
        "added": {
            "n": len(non_code),
            "per_family": {f: len(q) for f, q in sorted(non_code_families.items())},
            "gold_plane_mix": gold_plane_mix(non_code),
            "seed": 20260819,
            "max_mentions_per_gold_document": 4,
            "leakage_note": leakage_note(corpus, non_code),
        },
        "extended_set": {"n": len(extended), "gold_plane_mix": gold_plane_mix(extended)},
        "type_plane_gap": "no mechanical derivation of a TYPE-plane gold label exists in this "
                          "tree: the type plane is a proxy built from the same source files as "
                          "the code plane, and nothing references it as an artifact. The type "
                          "plane therefore still has 0 gold labels and its marginal contribution "
                          "remains untested (plan 13). Closing it needs real type artifacts, "
                          "not a better query rule.",
        "results": ext_results,
    }

    nc_single = evaluate(bm25_all, non_code, KS, family="non_code_only").as_dict(KS)
    nc_rr = evaluate(no_fusion, non_code, KS, family="non_code_only").as_dict(KS)
    nc_union = evaluate(union, non_code, KS, family="non_code_only").as_dict(KS)
    nc_code = evaluate(bm25_code, non_code, KS, family="non_code_only").as_dict(KS)
    report["kill_criterion_14_3"] = {
        "criterion": "four independent indices perform equivalently to cross-plane fusion",
        "true_fusion_arm_present": False,
        "verdict": "NOT DECIDABLE AS STATED — no cross-plane fusion retriever exists in this "
                   "slice, so the criterion has no second arm. What IS measurable here is the "
                   "weaker question 'four independent indices vs ONE JOINT index'.",
        "on_the_frozen_600": "structurally undecidable even for the weaker question: every gold "
                             "label is a code document, so any method that spends a slot on a "
                             "non-code plane can only lose, and a code-only index cannot be beaten",
        "on_non_code_gold_labels": {
            "n": len(non_code),
            "bm25_code_only_hits_at_10": nc_code["hits_at"]["10"],
            "four_plane_no_fusion_hits_at_10": nc_rr["hits_at"]["10"],
            "union_no_fusion_hits_at_10": nc_union["hits_at"]["10"],
            "bm25_single_index_all_planes_hits_at_10": nc_single["hits_at"]["10"],
            "reading": "on gold labels the code plane cannot hold, ONE joint index beats every "
                       "no-fusion arm. That is evidence AGAINST 'four independent indices "
                       "perform equivalently' for the joint-index comparison — but a joint "
                       "index is not cross-plane fusion, so the plan's criterion itself stays "
                       "open until a fusion arm exists.",
        },
        "what_would_close_it": "a real cross-plane fusion retriever, plus gold labels in all "
                               "four planes (the type plane still has none)",
    }

    # Construction artefact, measured instead of merely disclosed: a
    # knowledge_ref query is lifted from a Markdown file that the all-planes
    # index also contains, so that file can out-rank the code file it talks
    # about.  This penalises the single-index retriever for a property of the
    # query set, not of the retriever.
    ref_queries = families.get("knowledge_ref", [])
    self_hits = 0
    self_rank_sum = 0
    for query in ref_queries:
        source_locator = query.qid.split(":")[1]
        hits = bm25_all.query(query.text, k=max(KS))
        rank = rank_of(hits, f"knowledge:{source_locator}")
        if rank:
            self_hits += 1
            self_rank_sum += rank
    report["query_set_artefact"] = {
        "family": "knowledge_ref",
        "n": len(ref_queries),
        "source_document_in_top10_of_single_index": self_hits,
        "fraction": round(self_hits / len(ref_queries), 4) if ref_queries else 0.0,
        "mean_rank_when_present": round(self_rank_sum / self_hits, 3) if self_hits else 0.0,
        "note": "the query's own source Markdown file competing with the gold code file",
    }

    # Who rescues whom: the aggregate deltas above are net, these are gross.
    kmax = max(KS)
    ranks = {
        "bm25_code_only": rank_vector(bm25_code, queries, kmax),
        "graph_code_only": rank_vector(graph, queries, kmax),
        "graph_rewired": rank_vector(graph_rewired, queries, kmax),
        "four_plane_no_fusion": rank_vector(no_fusion, queries, kmax),
        "union_no_fusion": rank_vector(union, queries, kmax),
        "bm25_single_index_all_planes": rank_vector(bm25_all, queries, kmax),
    }
    report["crosstabs_at_10"] = {
        "graph_vs_bm25_code_only": {
            "a": "bm25_code_only",
            "b": "graph_code_only",
            **crosstab(ranks["bm25_code_only"], ranks["graph_code_only"], kmax),
        },
        "graph_vs_rewired_control": {
            "a": "graph_rewired",
            "b": "graph_code_only",
            **crosstab(ranks["graph_rewired"], ranks["graph_code_only"], kmax),
        },
        "no_fusion_vs_single_index": {
            "a": "four_plane_no_fusion",
            "b": "bm25_single_index_all_planes",
            **crosstab(ranks["four_plane_no_fusion"], ranks["bm25_single_index_all_planes"], kmax),
        },
        "no_fusion_vs_code_only": {
            "a": "four_plane_no_fusion",
            "b": "bm25_code_only",
            **crosstab(ranks["four_plane_no_fusion"], ranks["bm25_code_only"], kmax),
        },
        # The two the correction turns on: the un-starved no-fusion arm against
        # the code-only control, and against the comparator the spec names.
        "union_no_fusion_vs_code_only": {
            "a": "union_no_fusion",
            "b": "bm25_code_only",
            **crosstab(ranks["union_no_fusion"], ranks["bm25_code_only"], kmax),
        },
        "union_no_fusion_vs_single_index": {
            "a": "union_no_fusion",
            "b": "bm25_single_index_all_planes",
            **crosstab(ranks["union_no_fusion"], ranks["bm25_single_index_all_planes"], kmax),
        },
    }

    # Post-hoc sensitivity: NOT a tuned claim, printed so the frozen alpha=0.5
    # cannot be mistaken for a lucky pick.
    sensitivity = []
    for alpha in SENSITIVITY_ALPHAS:
        variant = CodeGraphRetriever(corpus, alpha=alpha, name=f"graph_alpha_{alpha}")
        sensitivity.append(evaluate(variant, queries, KS, family="all").as_dict(KS))
    report["post_hoc_sensitivity"] = {
        "note": "explored AFTER the frozen run; not used to select the headline configuration",
        "runs": sensitivity,
    }

    print(json.dumps(report, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
