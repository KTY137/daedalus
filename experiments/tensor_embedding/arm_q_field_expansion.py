"""Arm Q -- graph-assisted query expansion ("field expansion fuer Code").

EXPERIMENT tensor-embedding-v4, Arm Q (SPEC addendum frozen 2026-08-25 before
this measurement). Idea: BM25's one weakness is vocabulary mismatch. The Twin
knows which names belong together structurally. Expand the query through the
graph, then plain BM25. No learning.

LEAKAGE LOCK (first, per query, before anchor search): the node
``knowledge:doc:<page>`` and ALL its edges are removed from the working graph
of that query. Otherwise the page's own ``mentions`` edges feed the scrubbed
backtick spans straight back into the query as an echo. Among the relations
this arm consumes, only ``mentions`` is incident to doc nodes; the lock is
applied to the mention maps before anchors are searched, and anchoring itself
is lexical over concept names (no doc edges consulted).

ALGORITHM
  1. lock the query page's doc node out of the working graph;
  2. anchors: a knowledge:concept: node is an anchor iff ALL of its
     split_identifier word pieces occur in the query tokens (conservative;
     0 anchors => query unchanged, counted and reported);
  3. expansion terms per anchor over the locked graph:
     (a) symbols the concept documents (documents edge) -> their name tokens;
     (b) structural siblings: other fields/methods of the same class resp.
         other symbols of the same module as those symbols; for a documented
         class the class's own fields/methods count as members of "the same
         class" (that IS the owner's field expansion) -- noted as an
         interpretation of (b);
     (c) concepts co-mentioned with the anchor on OTHER pages;
     all terms split_identifier'd, lowercased, deduplicated, tokens already in
     the query excluded;
  4. weighting: original tokens 1.0, expansion tokens w; the BM25 class is not
     touched -- its rank() logic is copied here with a per-term weight factor
     (and an inverted index for speed; identical scores, identical tie-break:
     stable sort over sorted file ids);
  5. cap: at most `cap` expansion tokens per query, ordered by frequency over
     all anchors (ties broken alphabetically);
  6. sweep w in {0.15, 0.3, 0.5} x cap in {15, 30}; the win condition is
     checked ONLY against the pre-declared default (w=0.3, cap=30), the rest
     is sensitivity analysis.

Relations has_type/param_type/returns_type are listed as relevant in the
tasking but no algorithm step (a)-(c) consumes them; they are left unused
rather than inventing a step (recorded as a deviation note in the JSON).

Win conditions (frozen in runs/tensor_embedding_v4/SPEC.md):
  Q1: R@10 > 0.482 at default;  Q2: R@1 > 0.167 at default.

Run:  python experiments/tensor_embedding/arm_q_field_expansion.py
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import bench_crossplane as bench  # noqa: E402  (collect, BM25, recall_at, split_identifier)

TCT_ROOT = pathlib.Path("C:/Users/nukei/Desktop/project_tct")
TRIPLES = REPO / "runs" / "tensor_embedding_v3" / "triples_tct_after2.tsv"
OUT = REPO / "runs" / "tensor_embedding_v4" / "arm_q.json"

KS = (1, 5, 10, 25)
REFERENCE_BM25 = {1: 0.167, 5: 0.387, 10: 0.482, 25: 0.643}
DEFAULT_W, DEFAULT_CAP = 0.3, 30
SWEEP = [(w, cap) for w in (0.15, 0.3, 0.5) for cap in (15, 30)]
STRUCT_RELS = ("has_field", "has_method", "defines_func", "defines_class")
CONCEPT_PREFIX = "knowledge:concept:"


class Graph:
    """Global graph views for the relations Arm Q consumes."""

    def __init__(self, path: pathlib.Path):
        self.mentions_by_doc: dict[str, set[str]] = collections.defaultdict(set)
        self.docs_by_concept: dict[str, set[str]] = collections.defaultdict(set)
        self.documents_by_concept: dict[str, set[str]] = collections.defaultdict(set)
        self.children: dict[str, set[str]] = collections.defaultdict(set)
        self.parents: dict[str, set[str]] = collections.defaultdict(set)
        concepts: set[str] = set()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line:
                continue
            head, rel, tail = line.split("\t")
            if rel == "mentions":
                self.mentions_by_doc[head].add(tail)
                self.docs_by_concept[tail].add(head)
                concepts.add(tail)
            elif rel == "documents":
                self.documents_by_concept[head].add(tail)
                concepts.add(head)
            elif rel in STRUCT_RELS:
                self.children[head].add(tail)
                self.parents[tail].add(head)
        # Lexical index over concept names (anchoring is name-based, not edge-based).
        self.concept_pieces: dict[str, tuple[str, ...]] = {}
        for node in concepts:
            pieces = tuple(bench.split_identifier(node[len(CONCEPT_PREFIX):]))
            if pieces:
                self.concept_pieces[node] = pieces


def symbol_name_tokens(node: str) -> list[str]:
    """Name tokens of a code:/type: symbol node (qualname after '#', else stem)."""
    rest = node.split(":", 2)[2]
    name = rest.split("#", 1)[1] if "#" in rest else pathlib.Path(rest).stem
    return bench.split_identifier(name)


def expansion_terms(graph: Graph, page: str, qset: set[str]) -> tuple[list[tuple[str, int]], int]:
    """(ordered expansion tokens with counts, anchor count) for one query.

    Step 1 -- LEAKAGE LOCK, before anything else: the query page's doc node
    and all its edges are excluded from every graph view used below.
    """
    locked_doc = "knowledge:doc:" + page

    def docs_of(concept: str) -> set[str]:
        return graph.docs_by_concept.get(concept, set()) - {locked_doc}

    def mentions_of(doc: str) -> set[str]:
        # callers only pass docs != locked_doc; guard anyway
        if doc == locked_doc:
            return set()
        return graph.mentions_by_doc.get(doc, set())

    # Step 2 -- anchors (lexical, conservative: ALL pieces must be query tokens).
    anchors = sorted(
        node for node, pieces in graph.concept_pieces.items()
        if all(p in qset for p in pieces)
    )

    # Step 3 -- expansion terms over the locked graph.
    counts: collections.Counter[str] = collections.Counter()
    for anchor in anchors:
        produced: list[str] = []
        for sym in sorted(graph.documents_by_concept.get(anchor, ())):
            produced += symbol_name_tokens(sym)                      # (a)
            for member in graph.children.get(sym, ()):               # (b) own members
                produced += symbol_name_tokens(member)
            for parent in graph.parents.get(sym, ()):                # (b) siblings
                for sib in graph.children.get(parent, ()):
                    if sib != sym:
                        produced += symbol_name_tokens(sib)
        for doc in docs_of(anchor):                                  # (c) co-mentions
            for other in mentions_of(doc):
                if other != anchor:
                    produced += graph.concept_pieces.get(other, ())
        for tok in produced:
            if tok and tok not in qset:
                counts[tok] += 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered, len(anchors)


def build_postings(bm: "bench.BM25"):
    """Inverted index over the BM25 instance (class untouched)."""
    postings: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    for i, tf in enumerate(bm.tf):
        for term, freq in tf.items():
            postings[term].append((i, freq))
    return postings


def weighted_rank(bm: "bench.BM25", postings, weights: dict[str, float]) -> list[str]:
    """BM25.rank() logic with a per-term weight factor. Same scores at w=1,
    same deterministic tie-break (stable sort over sorted ids)."""
    scores = [0.0] * bm.n
    for term, w in weights.items():
        if term not in bm.df:
            continue
        idf = math.log(1 + (bm.n - bm.df[term] + 0.5) / (bm.df[term] + 0.5))
        for i, freq in postings[term]:
            denom = freq + bm.k1 * (1 - bm.b + bm.b * bm.len[i] / bm.avg)
            scores[i] += w * idf * freq * (bm.k1 + 1) / denom
    return [bm.ids[i] for i in sorted(range(bm.n), key=lambda i: -scores[i])]


def rrf(rank_a: list[str], rank_b: list[str], k: int = 60) -> list[str]:
    score: dict[str, float] = collections.defaultdict(float)
    for ranking in (rank_a, rank_b):
        for pos, doc in enumerate(ranking):
            score[doc] += 1.0 / (k + pos + 1)
    return sorted(score, key=lambda d: (-score[d], d))


def rank_pos(ranking: list[str], target: str) -> int:
    try:
        return ranking.index(target)
    except ValueError:
        return len(ranking)


def main() -> int:
    t0 = time.time()
    sources, pairs = bench.collect(TCT_ROOT)
    graph = Graph(TRIPLES)
    bm = bench.BM25(sources)
    postings = build_postings(bm)
    n = len(pairs)
    print(f"queries={n}  candidate source files={len(sources)}  "
          f"concepts indexed={len(graph.concept_pieces)}")

    combos = list(SWEEP)
    totals = {("bm25", None): {k: 0 for k in KS}}
    for combo in combos:
        totals[("expansion", combo)] = {k: 0 for k in KS}
    totals[("rrf_default", None)] = {k: 0 for k in KS}

    zero_anchor_pairs = 0
    zero_anchor_pages: set[str] = set()
    exp_len_before_cap: list[int] = []
    exp_len_default: list[int] = []
    anchors_per_query: list[int] = []
    per_query_default: list[dict] = []

    for pair in pairs:
        qtokens = pair["query"].split()
        qset = set(qtokens)

        # Control: the untouched BM25 class.
        base_ranking = bm.rank(qtokens)
        base_hit = bench.recall_at(base_ranking, pair["target"], KS)
        for k in KS:
            totals[("bm25", None)][k] += base_hit[k]

        # Lock, anchor, expand (lock happens first inside expansion_terms).
        ordered_exp, n_anchors = expansion_terms(graph, pair["page"], qset)
        anchors_per_query.append(n_anchors)
        exp_len_before_cap.append(len(ordered_exp))
        if n_anchors == 0:
            zero_anchor_pairs += 1
            zero_anchor_pages.add(pair["page"])

        default_ranking = None
        for w, cap in combos:
            chosen = ordered_exp[:cap]
            if chosen:
                weights = {t: 1.0 for t in qset}
                for tok, _ in chosen:
                    weights[tok] = w
                ranking = weighted_rank(bm, postings, weights)
            else:
                ranking = base_ranking  # no anchors / no terms: query unchanged
            hit = bench.recall_at(ranking, pair["target"], KS)
            for k in KS:
                totals[("expansion", (w, cap))][k] += hit[k]
            if (w, cap) == (DEFAULT_W, DEFAULT_CAP):
                default_ranking = ranking
                exp_len_default.append(len(chosen))

        # Kuer: RRF(bm25+expansion@default, doc_neighbour).
        neighbour = bench.doc_neighbour_rank(pair, pairs, sources)
        fused = rrf(default_ranking, neighbour)
        fhit = bench.recall_at(fused, pair["target"], KS)
        for k in KS:
            totals[("rrf_default", None)][k] += fhit[k]

        base_pos = rank_pos(base_ranking, pair["target"])
        def_pos = rank_pos(default_ranking, pair["target"])
        per_query_default.append({
            "page": pair["page"], "target": pair["target"],
            "bm25_rank": base_pos + 1, "expansion_rank": def_pos + 1,
            "delta": base_pos - def_pos,  # positive = improvement
        })

    def ratios(row: dict[int, int]) -> dict[str, float]:
        return {f"@{k}": round(row[k] / n, 4) for k in KS}

    bm25_res = ratios(totals[("bm25", None)])
    control_ok = all(round(bm25_res[f"@{k}"], 3) == REFERENCE_BM25[k] for k in KS)

    default_res = ratios(totals[("expansion", (DEFAULT_W, DEFAULT_CAP))])
    rrf_res = ratios(totals[("rrf_default", None)])
    q1_met = default_res["@10"] > 0.482
    q2_met = default_res["@1"] > 0.167

    by_delta = sorted(per_query_default, key=lambda r: (-r["delta"], r["page"], r["target"]))
    improvements = [r for r in by_delta if r["delta"] > 0][:5]
    regressions = [r for r in sorted(per_query_default,
                                     key=lambda r: (r["delta"], r["page"], r["target"]))
                   if r["delta"] < 0][:5]

    payload = {
        "experiment": "tensor-embedding-v4 / Arm Q -- graph-assisted query expansion",
        "spec": "runs/tensor_embedding_v4/SPEC.md (addendum Arm Q, frozen 2026-08-25)",
        "date": "2026-08-25",
        "root": str(TCT_ROOT),
        "substrate": str(TRIPLES.relative_to(REPO)),
        "queries": n,
        "candidate_files": len(sources),
        "chance_recall@10": round(10 / len(sources), 5),
        "leakage_lock": ("knowledge:doc:<page> and all its edges removed from the "
                         "working graph BEFORE anchor search, per query"),
        "control": {
            "bm25_pure": bm25_res,
            "reference": {f"@{k}": v for k, v in REFERENCE_BM25.items()},
            "reproduced": control_ok,
        },
        "default": {
            "w": DEFAULT_W, "cap": DEFAULT_CAP,
            "bm25_plus_expansion": default_res,
            "rrf_expansion_doc_neighbour": rrf_res,
        },
        "sweep": [
            {"w": w, "cap": cap, **ratios(totals[("expansion", (w, cap))])}
            for w, cap in combos
        ],
        "win_conditions": {
            "Q1": {"metric": "R@10", "threshold": 0.482,
                   "value": default_res["@10"], "met": q1_met},
            "Q2": {"metric": "R@1", "threshold": 0.167,
                   "value": default_res["@1"], "met": q2_met},
        },
        "diagnostics": {
            "zero_anchor_queries": zero_anchor_pairs,
            "zero_anchor_pages": sorted(zero_anchor_pages),
            "mean_anchors_per_query": round(sum(anchors_per_query) / n, 2),
            "mean_expansion_tokens_before_cap": round(sum(exp_len_before_cap) / n, 2),
            "mean_expansion_tokens_default_cap": round(sum(exp_len_default) / n, 2),
            "top5_improvements": improvements,
            "top5_regressions": regressions,
        },
        "deviation_notes": [
            "step (b): for a documented class symbol its own fields/methods are "
            "included as members of 'the same class' (owner's field-expansion "
            "intent); pure module siblings are also included",
            "has_type/param_type/returns_type are listed as relevant relations "
            "but no algorithm step consumes them; left unused",
        ],
        "runtime_seconds": round(time.time() - t0, 1),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"control bm25   " + "  ".join(f"R@{k}={bm25_res[f'@{k}']:.3f}" for k in KS)
          + f"  reproduced={control_ok}")
    for w, cap in combos:
        row = ratios(totals[("expansion", (w, cap))])
        tag = "  <-- default" if (w, cap) == (DEFAULT_W, DEFAULT_CAP) else ""
        print(f"w={w:<4} cap={cap:<3} " + "  ".join(f"R@{k}={row[f'@{k}']:.3f}" for k in KS) + tag)
    print(f"rrf(default, doc_neighbour) " + "  ".join(f"R@{k}={rrf_res[f'@{k}']:.3f}" for k in KS))
    print(f"Q1 (R@10 > 0.482): {'MET' if q1_met else 'NOT MET'}  value={default_res['@10']}")
    print(f"Q2 (R@1  > 0.167): {'MET' if q2_met else 'NOT MET'}  value={default_res['@1']}")
    print(f"zero-anchor queries: {zero_anchor_pairs}/{n}")
    print(f"wrote {OUT}  ({payload['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
