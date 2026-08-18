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
from s08_corpus import (  # noqa: E402
    build_corpus,
    corpus_digest,
    cross_plane_edge_census,
)
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


CROSSTAB_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("graph_vs_bm25_code_only", "bm25_code_only", "graph_code_only"),
    ("graph_vs_rewired_control", "graph_rewired", "graph_code_only"),
    ("no_fusion_vs_single_index", "four_plane_no_fusion", "bm25_single_index_all_planes"),
    ("no_fusion_vs_code_only", "four_plane_no_fusion", "bm25_code_only"),
    # The two the earlier correction turned on: the un-starved no-fusion arm
    # against the code-only control, and against the comparator the spec names.
    ("union_no_fusion_vs_code_only", "union_no_fusion", "bm25_code_only"),
    ("union_no_fusion_vs_single_index", "union_no_fusion", "bm25_single_index_all_planes"),
)


def crosstabs_by_cutoff(ranks: dict[str, list[int]]) -> dict:
    """Every pair at EVERY cutoff in ``KS``.  There is deliberately no ``ks``
    argument: a caller must not be able to pin this to one flattering cutoff.

    The first two runs of this slice reported crosstabs at k=10 alone.  For the
    graph pairs that is the one cutoff where the graph wins, and the sign flips
    below it: against the degree-preserving rewired control the real graph is
    -63 at k=1, -7 at k=5 and +6 at k=10.  Reporting only the last of those
    understates kill criterion 14.2 by an order of magnitude, in the direction
    that favours the hypothesis -- the same defect class as the substituted
    comparator, one level down.
    """
    cutoffs: dict[str, dict] = {}
    for k in KS:
        row: dict[str, dict] = {}
        for name, a, b in CROSSTAB_PAIRS:
            counts = crosstab(ranks[a], ranks[b], k)
            row[name] = {
                "a": a,
                "b": b,
                **counts,
                "net_b_minus_a": counts["only_b"] - counts["only_a"],
                "discordant": counts["only_a"] + counts["only_b"],
            }
        cutoffs[str(k)] = row
    return {
        "note": "net = only_b - only_a, positive means B wins. Read every cutoff: for the "
                "graph pairs the sign flips between k=1 and k=10.",
        "cutoffs": cutoffs,
    }


def reachable_planes(retriever, queries, kmax: int) -> dict:
    """Which planes this arm can put in front of a user AT ALL, measured.

    An arm whose index holds only code documents cannot be beaten -- or beaten
    back -- on a query whose gold label is not a code document.  It scores zero
    on every such query no matter what the graph does, and so does its control.
    That is a property of the instrument, and it decides what a comparison
    involving that arm is able to refute before any interval is computed.
    """
    counts: dict[str, int] = {}
    for query in queries:
        for hit in retriever.query(query.text, k=kmax):
            counts[hit.plane] = counts.get(hit.plane, 0) + 1
    return {
        "returned_doc_planes": dict(sorted(counts.items())),
        "can_return_non_code": any(plane != "code" for plane in counts),
    }


def informative_queries(a_ranks: list[int], b_ranks: list[int]) -> dict:
    """Discordant pairs per cutoff: the ONLY queries that carry information here.

    Two arms that both miss a query agree by default.  Padding a comparison with
    queries neither arm can answer adds denominator and no evidence, which
    shrinks a difference-of-proportions and its interval towards zero -- i.e.
    towards EQUIVALENT -- without a single new observation.  An equivalence test
    run on such a padded set will fire a KILL verdict sooner and on less.
    """
    out: dict[str, int] = {}
    for k in KS:
        counts = crosstab(a_ranks, b_ranks, k)
        out[str(k)] = counts["only_a"] + counts["only_b"]
    return out


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
    report["corpus"] = {
        **corpus.stats,
        "build_seconds": round(build_seconds, 3),
        "digest_sha256": corpus_digest(corpus),
    }

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
    report["crosstabs_by_cutoff"] = crosstabs_by_cutoff(ranks)

    # ---------------------------------------------------------------------
    # DECIDABILITY AUDIT.  Asked after the s10 evaluator observed that on the
    # frozen 600 every gold label is a code document, so criterion 14.3 is
    # structurally unfalsifiable there in the direction that favours the
    # hypothesis.  The question this answers is not "what do the arms score"
    # but "can this query set produce BOTH verdicts at all".  A kill instrument
    # can be blind for reasons that have nothing to do with its statistics.
    audit_sets = {
        "frozen_600": queries,
        "added_non_code_138": non_code,
        "extended_738": extended,
    }
    audit_ranks = {
        name: {
            set_name: rank_vector(arm, qs, max(KS))
            for set_name, qs in audit_sets.items()
        }
        for name, arm in (
            ("bm25_code_only", bm25_code),
            ("graph_code_only", graph),
            ("graph_rewired", graph_rewired),
            ("four_plane_no_fusion", no_fusion),
            ("union_no_fusion", union),
            ("bm25_single_index_all_planes", bm25_all),
        )
    }
    census = cross_plane_edge_census(corpus)
    report["decidability_audit"] = {
        "question": "does a query set with non-code gold labels make kill criteria 14.2 and "
                    "14.3 resolvable in BOTH directions, or only in one?",
        "corpus_digest_sha256": corpus_digest(corpus),
        "gold_plane_distribution": {
            set_name: {"n": len(qs), "mix": gold_plane_mix(qs)}
            for set_name, qs in audit_sets.items()
        },
        "planes_that_can_hold_a_gold_label": {
            "code": True,
            "knowledge": True,
            "data": True,
            "type": False,
        },
        "graph_edge_census": {
            **census,
            "reading": "criterion 14.2 names degree-preserving randomized CROSS-PLANE edges. "
                       "This graph has %d of them: every edge joins two code modules, so the "
                       "rewiring control randomises an intra-code-plane import/call graph. "
                       "The object the criterion speaks about does not exist in this slice."
                       % census["cross_plane_edges"],
        },
        "arm_reachable_planes": {
            name: reachable_planes(arm, extended, max(KS))
            for name, arm in (
                ("bm25_code_only", bm25_code),
                ("graph_code_only", graph),
                ("graph_rewired", graph_rewired),
                ("four_plane_no_fusion", no_fusion),
                ("union_no_fusion", union),
                ("bm25_single_index_all_planes", bm25_all),
            )
        },
        "criterion_14_2": {
            "text": "degree-preserving randomized cross-plane edges perform equivalently",
            "arm_a": "graph_rewired",
            "arm_b": "graph_code_only",
            "second_arm_exists": True,
            "arms_are_cross_plane": census["cross_plane_edges"] > 0,
            "hits_at_10": {
                set_name: {
                    "graph_code_only": sum(
                        1 for r in audit_ranks["graph_code_only"][set_name] if 1 <= r <= 10
                    ),
                    "graph_rewired": sum(
                        1 for r in audit_ranks["graph_rewired"][set_name] if 1 <= r <= 10
                    ),
                }
                for set_name in audit_sets
            },
            "informative_queries_by_cutoff": {
                set_name: informative_queries(
                    audit_ranks["graph_rewired"][set_name],
                    audit_ranks["graph_code_only"][set_name],
                )
                for set_name in audit_sets
            },
            "verdict": "NOT RESOLVABLE IN EITHER DIRECTION BY THIS QUERY SET, for two "
                       "independent reasons. (1) Both arms index the code plane only, so on "
                       "all 138 non-code-gold queries both score 0 and every one of them is "
                       "concordant: the added labels contribute ZERO informative queries at "
                       "every cutoff. The discordant counts on the extended 738 are identical "
                       "to those on the frozen 600 while n grows by 23%, so an equivalence "
                       "test run on the extended set reports a SMALLER difference and a "
                       "TIGHTER interval from no new evidence -- it manufactures the KILL "
                       "verdict out of padding. (2) The graph has 0 cross-plane edges, so what "
                       "the control randomises is not what the criterion names.",
        },
        "criterion_14_3": {
            "text": "four independent indices perform equivalently to cross-plane fusion",
            "arm_a": "four_plane_no_fusion / union_no_fusion",
            "arm_b": None,
            "second_arm_exists": False,
            "weaker_proxy_arm_b": "bm25_single_index_all_planes (ONE JOINT INDEX, not fusion)",
            "proxy_hits_at_10": {
                set_name: {
                    name: sum(1 for r in audit_ranks[name][set_name] if 1 <= r <= 10)
                    for name in (
                        "bm25_code_only",
                        "four_plane_no_fusion",
                        "union_no_fusion",
                        "bm25_single_index_all_planes",
                    )
                }
                for set_name in audit_sets
            },
            "proxy_informative_queries_by_cutoff": {
                set_name: informative_queries(
                    audit_ranks["union_no_fusion"][set_name],
                    audit_ranks["bm25_single_index_all_planes"][set_name],
                )
                for set_name in audit_sets
            },
            "verdict": "THE CRITERION AS WRITTEN IS STILL NOT RESOLVABLE IN EITHER DIRECTION: "
                       "no cross-plane fusion retriever exists in this slice, so it has one "
                       "arm on any query set. Missing arm, not missing labels -- the non-code "
                       "gold labels cannot fix it. What they DO fix is the weaker joint-index "
                       "proxy: on the frozen 600 the no-fusion arms win (union +53 at k=10), "
                       "on the added 138 the joint index wins (+48 at k=10), both with "
                       "non-zero discordant counts. That proxy question is now two-sided, "
                       "which it was not before; the plan's criterion is not.",
        },
        "what_a_kill_verdict_from_this_query_set_would_mean": {
            "14_2": "AN ARTEFACT. The non-code labels add denominator and no information to "
                    "it, and the rewired control does not randomise cross-plane edges. A KILL "
                    "here would be evidence about the query set and the graph's scope, not "
                    "about the four-plane prior.",
            "14_3": "NOT PRODUCIBLE. With one arm the comparison cannot be run in either "
                    "direction. A KILL reported against it would be a category error.",
            "14_3_weaker_proxy": "EVIDENCE, with a named limit. The proxy is decidable in both "
                                 "directions on this query set and it points opposite ways on "
                                 "the two halves, which is a real finding about routing cost. "
                                 "It is not the plan's criterion and must not be reported as "
                                 "it.",
        },
        "what_would_make_them_resolvable": [
            "14.2: cross-plane edges to rewire (the graph currently has none), and arms whose "
            "index can return the plane the gold label lives in",
            "14.3: a real cross-plane fusion retriever as the second arm",
            "both: gold labels in the type plane, which no mechanical rule in this tree yields",
        ],
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
