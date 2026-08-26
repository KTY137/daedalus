"""Arm N: Personalized PageRank -- query-dependent structure.

doc_neighbour (R@10=0.333) is a query-INDEPENDENT popularity prior: it ranks
what sibling pages link to, the same list for every query from the same page
set. This arm builds the query-dependent version: restart a random walk at the
asking page's knowledge:doc: node and score the PPR mass that lands on the 411
candidate code:module: nodes.

Split (exact replication of arm J, seed 31): documents_file edges in file
order, rng.permutation, first max(1, int(0.2*168)) = 33 stay in training,
135 held out. HOLDOUT IS GLOBAL: all 135 test edges are absent from the PPR
graph for every query (conservative -- the task allowed per-query masking;
global means the 33 keep-pairs still see their own edge, so the honest
comparison row is the 135-test subset, reported separately).

Weighting: uniform, plus a relation-weighted variant w(rel) = 1/count(rel).
Justification: `mentions` is 11070 of 36408 edges (30%) and is lexically
derived (backtick-span == symbol name), the noisiest relation; under uniform
weights the walk mostly follows it. Inverse relation frequency is
deterministic and parameter-free: each relation TYPE gets equal total
transition mass. Both variants are reported.

Controls (the day's error list, item 4):
  * zero-control: an isolated restart node puts 0 mass on every candidate;
    with pessimistic tie-ranking this MUST give 0 hits at every k.
  * target-restart control: seeding PPR at the target module itself must rank
    the target ~first (restart mass alpha dominates); checks the node<->file
    mapping and the recall plumbing end to end.

PPR-alone metrics use PESSIMISTIC tie-ranking (target placed after all
equal-scored candidates), so zero-mass targets can never score by alphabet.
BM25 numbers here use the benchmark's own stable-sort convention, unchanged.

Run:  python experiments/tensor_embedding/arm_n_ppr.py [repo-root]
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench_crossplane as B

REPO = pathlib.Path(__file__).resolve().parents[2]
V3 = REPO / "runs" / "tensor_embedding_v3"
OUT = REPO / "runs" / "tensor_embedding_v4"
TAG = "tct_after2"
ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                    "C:/Users/nukei/Desktop/project_tct").resolve()
ALPHA = 0.15
MAX_IT = 50
TOL = 1e-8
K_RRF = 60.0
KS = (1, 5, 10, 25)

t0 = time.time()

# ---------------------------------------------------------------- split (arm J)
rows = [l.split("\t") for l in
        (V3 / f"triples_{TAG}.tsv").read_text(encoding="utf-8").splitlines()]
doc_edges = [(h, r, t) for h, r, t in rows if r == "documents_file"]
other = [(h, r, t) for h, r, t in rows if r != "documents_file"]
rng = np.random.default_rng(31)
perm = rng.permutation(len(doc_edges))
n_keep = max(1, int(0.2 * len(doc_edges)))
keep = [doc_edges[i] for i in perm[:n_keep]]
test = [doc_edges[i] for i in perm[n_keep:]]
train = other + keep
ents = {n for h, _, t in train for n in (h, t)}
test = [x for x in test if x[0] in ents and x[2] in ents]
print(f"documents_file: {len(doc_edges)} gesamt -> {len(keep)} im Training, "
      f"{len(test)} zurueckgehalten (global aus dem Graphen)")

# self-check (1): no held-out edge anywhere in the graph
train_set = set(train)
assert not any(e in train_set for e in test), "held-out edge leaked into graph"

# ------------------------------------------------------------------- the graph
node_id: dict[str, int] = {}
for h, _, t in train:
    for n_ in (h, t):
        if n_ not in node_id:
            node_id[n_] = len(node_id)
n_nodes = len(node_id)
m = len(train)
src = np.empty(2 * m, dtype=np.int64)
dst = np.empty(2 * m, dtype=np.int64)
rel_of: list[str] = []
for i, (h, r, t) in enumerate(train):
    a, b_ = node_id[h], node_id[t]
    src[2 * i], dst[2 * i] = a, b_
    src[2 * i + 1], dst[2 * i + 1] = b_, a
    rel_of.append(r)
    rel_of.append(r)
rel_count = collections.Counter(r for _, r, _ in train)
w_uniform = np.ones(2 * m)
w_relinv = np.array([1.0 / rel_count[r] for r in rel_of])
print(f"Graph: {n_nodes} Knoten, {m} ungerichtete Kanten")


def make_ppr(w: np.ndarray):
    deg = np.bincount(src, weights=w, minlength=n_nodes)
    assert (deg > 0).all(), "node without edges -- impossible by construction"
    edge_c = w / deg[src]

    def run(seed: int) -> tuple[np.ndarray, int]:
        e = np.zeros(n_nodes)
        e[seed] = 1.0
        p = e.copy()
        for it in range(1, MAX_IT + 1):
            p_new = ALPHA * e + (1 - ALPHA) * np.bincount(
                dst, weights=edge_c * p[src], minlength=n_nodes)
            delta = np.abs(p_new - p).sum()
            p = p_new
            if delta < TOL:
                return p, it
        return p, MAX_IT

    return run


ppr_by_weighting = {"uniform": make_ppr(w_uniform), "relinv": make_ppr(w_relinv)}

# ------------------------------------------------- benchmark pairs + candidates
sources, pairs = B.collect(ROOT)
bm = B.BM25(sources)
cands = sorted(sources)                       # 411, same order as BM25.ids
cand_pos = {c: i for i, c in enumerate(cands)}
cand_idx = np.array([node_id.get(f"code:module:{c}", -1) for c in cands])
n_cand = len(cands)
print(f"Benchmark: {len(pairs)} Paare, {n_cand} Kandidaten, "
      f"{int((cand_idx >= 0).sum())} Kandidaten im Graphen")

test_pt = {(h[len("knowledge:doc:"):], t[len("code:module:"):]) for h, _, t in test}
keep_pt = {(h[len("knowledge:doc:"):], t[len("code:module:"):]) for h, _, t in keep}
unmapped = [p for p in pairs
            if (p["page"], p["target"]) not in test_pt
            and (p["page"], p["target"]) not in keep_pt]
print(f"Split-Abdeckung: {sum((p['page'], p['target']) in test_pt for p in pairs)} Test-, "
      f"{sum((p['page'], p['target']) in keep_pt for p in pairs)} Keep-, "
      f"{len(unmapped)} unzugeordnete Paare")


def cand_scores(p_vec: np.ndarray) -> np.ndarray:
    s = np.zeros(n_cand)
    mask = cand_idx >= 0
    s[mask] = p_vec[cand_idx[mask]]
    return s


def pessimistic_rank(s: np.ndarray, target: str) -> int:
    ts = s[cand_pos[target]]
    return int((s > ts).sum() + (s == ts).sum() - 1)


def stable_order(s: np.ndarray) -> list[str]:
    return [cands[i] for i in np.argsort(-s, kind="stable")]


# ------------------------------------------------------------- per-query loops
ppr_cache: dict[tuple[str, str], np.ndarray] = {}
iters_seen: list[int] = []
unscored_pages: set[str] = set()

records = []      # one dict per pair with all ranks
for pair in pairs:
    page_node = f"knowledge:doc:{pair['page']}"
    rec = {"page": pair["page"], "target": pair["target"],
           "subset": ("test" if (pair["page"], pair["target"]) in test_pt
                      else "keep" if (pair["page"], pair["target"]) in keep_pt
                      else "unmapped")}
    q = pair["query"].split()
    rank_bm = bm.rank(q)
    rank_dn = B.doc_neighbour_rank(pair, pairs, sources)
    pos_bm = {rel: i for i, rel in enumerate(rank_bm)}
    pos_dn = {rel: i for i, rel in enumerate(rank_dn)}
    rec["rank_bm25"] = rank_bm.index(pair["target"])
    rec["rank_dn"] = rank_dn.index(pair["target"])

    if page_node not in node_id:
        unscored_pages.add(pair["page"])
        rec["scoreable"] = False
        # fusion falls back to the available components only
        for wname in ppr_by_weighting:
            rec[f"rank_ppr_{wname}"] = None
        fused2 = sorted(cands, key=lambda r: (-(1.0 / (K_RRF + pos_bm[r])), r))
        fused3 = sorted(cands, key=lambda r: (-(1.0 / (K_RRF + pos_bm[r])
                                                + 1.0 / (K_RRF + pos_dn[r])), r))
        rec["rank_rrf2"] = fused2.index(pair["target"])
        rec["rank_rrf3"] = fused3.index(pair["target"])
    else:
        rec["scoreable"] = True
        for wname, runner in ppr_by_weighting.items():
            key = (wname, pair["page"])
            if key not in ppr_cache:
                p_vec, its = runner(node_id[page_node])
                ppr_cache[key] = p_vec
                iters_seen.append(its)
            s = cand_scores(ppr_cache[key])
            rec[f"rank_ppr_{wname}"] = pessimistic_rank(s, pair["target"])
            if wname == "uniform":
                pos_ppr = {rel: i for i, rel in enumerate(stable_order(s))}
                fused2 = sorted(cands, key=lambda r: (
                    -(1.0 / (K_RRF + pos_bm[r]) + 1.0 / (K_RRF + pos_ppr[r])), r))
                fused3 = sorted(cands, key=lambda r: (
                    -(1.0 / (K_RRF + pos_bm[r]) + 1.0 / (K_RRF + pos_ppr[r])
                      + 1.0 / (K_RRF + pos_dn[r])), r))
                rec["rank_rrf2"] = fused2.index(pair["target"])
                rec["rank_rrf3"] = fused3.index(pair["target"])
    records.append(rec)

# ---------------------------------------------------------------------- metrics
METHODS = ("bm25", "dn", "ppr_uniform", "ppr_relinv", "rrf2", "rrf3")


def agg(recs: list[dict]) -> dict:
    out = {}
    for meth in METHODS:
        key = f"rank_{meth}"
        ranks = [r[key] if r[key] is not None else n_cand for r in recs]
        out[meth] = {f"@{k}": round(sum(rk < k for rk in ranks) / len(recs), 4)
                     for k in KS}
    return out


all_pairs = records
test_pairs = [r for r in records if r["subset"] == "test"]
keep_pairs = [r for r in records if r["subset"] == "keep"]
res_all = agg(all_pairs)
res_test = agg(test_pairs)
res_keep = agg(keep_pairs) if keep_pairs else {}

# --------------------------------------------------------------------- controls
# zero-control: isolated restart -> all candidate mass 0 -> pessimistic rank 410
zero_hits = sum(pessimistic_rank(np.zeros(n_cand), r["target"]) < max(KS)
                for r in records)
assert zero_hits == 0, f"zero-control failed: {zero_hits} hits from ties"

# target-restart control on the 135 test pairs (uniform weights)
runner = ppr_by_weighting["uniform"]
tgt_cache: dict[str, np.ndarray] = {}
tgt_top1 = 0
tgt_n = 0
for r in test_pairs:
    node = f"code:module:{r['target']}"
    if node not in node_id:
        continue
    tgt_n += 1
    if r["target"] not in tgt_cache:
        tgt_cache[r["target"]], _ = runner(node_id[node])
    tgt_top1 += pessimistic_rank(cand_scores(tgt_cache[r["target"]]),
                                 r["target"]) < 1
control_target_restart = round(tgt_top1 / max(1, tgt_n), 4)

runtime = round(time.time() - t0, 1)

payload = {
    "arm": "N",
    "task": "wiki page -> source file it documents; PPR restart at the page node",
    "graph": {"nodes": n_nodes, "undirected_edges": m,
              "holdout": "GLOBAL: all 135 test documents_file edges removed for every query; 33 keep edges remain (their 33 pairs therefore see their own edge -> honest row = 135-test subset)",
              "weightings": {"uniform": "all edges weight 1",
                             "relinv": "w(rel)=1/count(rel); mentions is 30% of edges and lexically derived, inverse relation frequency gives each relation type equal total transition mass"}},
    "ppr": {"alpha": ALPHA, "max_iterations": MAX_IT, "tol": TOL,
            "iterations_used": {"min": int(min(iters_seen)), "max": int(max(iters_seen))},
            "tie_handling": "PPR-alone metrics: pessimistic (target after all ties); fusion rankings: stable alphabetical, same as BM25"},
    "queries": {"total": len(all_pairs), "test_subset": len(test_pairs),
                "keep_subset": len(keep_pairs), "unmapped": len(unmapped),
                "unscoreable_pages": sorted(unscored_pages)},
    "candidates": n_cand,
    "candidates_in_graph": int((cand_idx >= 0).sum()),
    "chance@10": round(10 / n_cand, 5),
    "fusion": f"reciprocal rank fusion, k={int(K_RRF)}; rrf2=bm25+ppr_uniform, rrf3=bm25+ppr_uniform+doc_neighbour",
    "results_all_168": res_all,
    "results_test_135": res_test,
    "results_keep_33": res_keep,
    "reference": {"bm25_168": 0.482, "doc_neighbour_168": 0.333,
                  "rrf_bm25_struct_168": 0.601, "bm25_135": 0.474,
                  "note": "reference values from arm J/K artifacts (R@10)"},
    "controls": {"zero_restart_hits_at_25": zero_hits,
                 "target_restart_R@1": control_target_restart,
                 "target_restart_n": tgt_n},
    "runtime_seconds": runtime,
    "seed_policy": "split rng seed 31 (arm J); PPR is deterministic, no stochastic component",
}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "arm_n.json").write_text(json.dumps(payload, indent=2) + "\n",
                                encoding="utf-8", newline="\n")

for label, res, nn in (("alle 168", res_all, len(all_pairs)),
                       ("Test 135", res_test, len(test_pairs)),
                       ("Keep 33", res_keep, len(keep_pairs))):
    if not res:
        continue
    print(f"\n[{label}] (n={nn})")
    for meth in METHODS:
        print(f"  {meth:12s} " + "  ".join(f"R@{k}={res[meth][f'@{k}']:.3f}" for k in KS))
print(f"\nKontrollen: zero-restart hits@25 = {zero_hits} (muss 0), "
      f"target-restart R@1 = {control_target_restart} (n={tgt_n}, soll ~1.0)")
print(f"Zufall@10 = {payload['chance@10']}, Laufzeit {runtime}s")
print(f"wrote {OUT / 'arm_n.json'}")
