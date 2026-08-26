"""Arm P: tensor algebra -- typed contraction features, no learning.

The Twin as tensor X[h,r,t]; the product of two relation slices is the typed
2-hop path count. This arm asks what the ALGEBRA ALONE pulls out of the Twin:
query-dependent features per (page, module) pair built purely by contraction
of bipartite relation slices, with the 135 held-out documents_file edges
removed from every slice.

Slices (from the TSV, WITHOUT the 135 test edges):
  M1 = doc x concept   (mentions)
  M2 = concept x symbol (documents)
  M3 = symbol x module  (parsed from the symbol ID: code:class:P#X -> code:module:P)
  M4 = doc x module     (documents_file, ONLY the 33 keep edges)
  M5 = doc x file       (links_to)

Features per (page, module), each a typed path, all log1p-damped:
  f1 = (M1@M2@M3)[page,module]      mentions -> documents -> in_module
  f2 = colsum(M4)[module]           training popularity (query-independent)
  f3 = (M1@M1^T@M4)[page,module]    pages sharing concepts -> their known modules
  f4 = (M5@M5^T@M4)[page,module]    pages linking the same files -> their known modules

Scorings: (1) f1 alone; (2) sum of per-query max-normalised features;
(3) RRF(k=60) of the best feature ranking with BM25 (bench_crossplane).

Leak audit measured up front: links_to has ZERO .py targets and ZERO overlap
with documents_file pairs, so M5 does not encode any held-out edge. A leak
CONTROL runs the full M4 (all 168 edges) as a feature: by construction every
target then scores positive and no page has more than 17 targets, so
R@25 MUST be 1.0 -- if it is not, the pipeline is broken.

Run:  python experiments/tensor_embedding/arm_p_contraction.py
"""
from __future__ import annotations

import collections
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench_crossplane as B

REPO = pathlib.Path(__file__).resolve().parents[2]
TSV = REPO / "runs" / "tensor_embedding_v3" / "triples_tct_after2.tsv"
OUT = REPO / "runs" / "tensor_embedding_v4"
ROOT = pathlib.Path("C:/Users/nukei/Desktop/project_tct")
KS = (1, 5, 10, 25)
K_RRF = 60.0

# ---------------------------------------------------------------- split ----
rows = [tuple(line.split("\t")) for line in
        TSV.read_text(encoding="utf-8").splitlines() if line.strip()]
doc_edges = [(h, t) for h, r, t in rows if r == "documents_file"]
assert len(doc_edges) == 168, f"expected 168 documents_file edges, got {len(doc_edges)}"
assert len(set(doc_edges)) == 168, "documents_file edges are not unique"

rng = np.random.default_rng(31)
perm = rng.permutation(len(doc_edges))
n_keep = max(1, int(0.2 * len(doc_edges)))          # 33
keep_idx = [int(i) for i in perm[:n_keep]]
test_idx = [int(i) for i in perm[n_keep:]]
train_edges = [doc_edges[i] for i in keep_idx]
test_edges = [doc_edges[i] for i in test_idx]
test_set = set(test_edges)
assert len(train_edges) == 33 and len(test_edges) == 135

# ------------------------------------------------------------ benchmark ----
sources, pairs = B.collect(ROOT)
cands = sorted(sources)
assert len(cands) == 411, f"expected 411 candidate files, got {len(cands)}"
assert len(pairs) == 168, f"expected 168 pairs, got {len(pairs)}"

pair_edges = {("knowledge:doc:" + p["page"], "code:module:" + p["target"])
              for p in pairs}
assert pair_edges == set(doc_edges), "TSV documents_file edges != collect() pairs"

# ------------------------------------------------- slices, test excluded ----
M1 = collections.defaultdict(collections.Counter)   # doc -> concept
M2 = collections.defaultdict(collections.Counter)   # concept -> symbol
M5 = collections.defaultdict(collections.Counter)   # doc -> file
for h, r, t in rows:
    if r == "mentions":
        M1[h][t] += 1
    elif r == "documents":
        M2[h][t] += 1
    elif r == "links_to":
        M5[h][t] += 1

def module_of(symbol: str) -> str:
    # code:class:TCT_app/x.py#Name / code:func:TCT_app/x.py#name -> code:module:TCT_app/x.py
    body = symbol.split(":", 2)[2]
    return "code:module:" + body.split("#", 1)[0]

# M3 folded into M2: concept -> Counter(module)
C2M = collections.defaultdict(collections.Counter)
for concept, syms in M2.items():
    for sym, w in syms.items():
        if sym.startswith(("code:class:", "code:func:")):
            C2M[concept][module_of(sym)] += w

M4 = collections.defaultdict(collections.Counter)   # doc -> module, 33 keep only
pop = collections.Counter()                          # f2
for h, t in train_edges:
    M4[h][t] += 1
    pop[t] += 1

M4_full = collections.defaultdict(collections.Counter)  # leak CONTROL only
for h, t in doc_edges:
    M4_full[h][t] += 1

# --------------------------------------------------------- leak audit ------
leak = {"test_edge_in_M4_train": 0, "test_edge_in_M5_as_file": 0,
        "links_to_py_targets": 0}
for h, r, t in rows:
    if r == "links_to" and t.endswith(".py"):
        leak["links_to_py_targets"] += 1
for h, t in test_edges:
    if M4[h].get(t):
        leak["test_edge_in_M4_train"] += 1
    file_node = "knowledge:file:" + t[len("code:module:"):]
    if M5[h].get(file_node):
        leak["test_edge_in_M5_as_file"] += 1
assert sum(leak.values()) == 0, f"LEAK: {leak}"

# ------------------------------------------------------------ features -----
def contract_features(doc: str) -> dict[str, collections.Counter]:
    """All four typed-path counts for one page, raw (pre-log1p)."""
    f1 = collections.Counter()
    for concept, w in M1[doc].items():
        for mod, w2 in C2M[concept].items():
            f1[mod] += w * w2
    f3 = collections.Counter()
    for d2, mods in M4.items():
        if d2 == doc:
            continue
        ov = sum(w * M1[d2][c] for c, w in M1[doc].items() if c in M1[d2])
        if ov:
            for mod, w2 in mods.items():
                f3[mod] += ov * w2
    f4 = collections.Counter()
    for d2, mods in M4.items():
        if d2 == doc:
            continue
        ov = sum(w * M5[d2][c] for c, w in M5[doc].items() if c in M5[d2])
        if ov:
            for mod, w2 in mods.items():
                f4[mod] += ov * w2
    return {"f1": f1, "f2": pop, "f3": f3, "f4": f4}

def damp(feat: collections.Counter) -> dict[str, float]:
    """log1p over the 411 candidates, keyed by rel path."""
    return {rel: math.log1p(feat.get("code:module:" + rel, 0)) for rel in cands}

def rank_of(scores: dict[str, float]) -> list[str]:
    return sorted(cands, key=lambda r: (-scores[r], r))

def norm(v: dict[str, float]) -> dict[str, float]:
    m = max(v.values())
    return {k: (x / m if m > 0 else 0.0) for k, x in v.items()}

# per unique page: feature vectors and rankings
page_feats: dict[str, dict] = {}
for p in pairs:
    doc = "knowledge:doc:" + p["page"]
    if doc in page_feats:
        continue
    raw = contract_features(doc)
    d = {name: damp(feat) for name, feat in raw.items()}
    s1 = d["f1"]
    s2_vec = {rel: sum(norm(d[name])[rel] for name in ("f1", "f2", "f3", "f4"))
              for rel in cands}
    ctrl = damp(M4_full[doc])
    page_feats[doc] = {
        "d": d, "s1_rank": rank_of(s1), "s2_rank": rank_of(s2_vec),
        "f_ranks": {name: rank_of(d[name]) for name in ("f1", "f2", "f3", "f4")},
        "ctrl_rank": rank_of(ctrl),
    }

# ------------------------------------------------------------ evaluate -----
bm = B.BM25(sources)
methods = ["bm25", "f1_only", "f2_only", "f3_only", "f4_only",
           "s1_f1", "s2_sum_norm", "rrf_s1_bm25", "rrf_s2_bm25",
           "control_full_M4"]
tot = {m: {sub: {k: 0 for k in KS} for sub in ("all", "test", "train")}
       for m in methods}
n_sub = {"all": 0, "test": 0, "train": 0}

def rrf(rank_a: list[str], rank_b: list[str]) -> list[str]:
    pa = {r: i for i, r in enumerate(rank_a)}
    pb = {r: i for i, r in enumerate(rank_b)}
    return sorted(cands,
                  key=lambda r: (-(1.0 / (K_RRF + pa[r]) + 1.0 / (K_RRF + pb[r])), r))

for p in pairs:
    doc = "knowledge:doc:" + p["page"]
    edge = (doc, "code:module:" + p["target"])
    subs = ["all", "test" if edge in test_set else "train"]
    for s in subs:
        n_sub[s] += 1
    pf = page_feats[doc]
    rank_bm = bm.rank(p["query"].split())
    rankings = {
        "bm25": rank_bm,
        "f1_only": pf["f_ranks"]["f1"], "f2_only": pf["f_ranks"]["f2"],
        "f3_only": pf["f_ranks"]["f3"], "f4_only": pf["f_ranks"]["f4"],
        "s1_f1": pf["s1_rank"], "s2_sum_norm": pf["s2_rank"],
        "rrf_s1_bm25": rrf(pf["s1_rank"], rank_bm),
        "rrf_s2_bm25": rrf(pf["s2_rank"], rank_bm),
        "control_full_M4": pf["ctrl_rank"],
    }
    for m, ranking in rankings.items():
        hit = B.recall_at(ranking, p["target"], KS)
        for s in subs:
            for k in KS:
                tot[m][s][k] += hit[k]

res = {m: {s: {f"@{k}": round(tot[m][s][k] / n_sub[s], 4) for k in KS}
           for s in ("all", "test", "train")} for m in methods}

best_feature = max(("s1_f1", "s2_sum_norm"), key=lambda m: res[m]["all"]["@10"])
control_ok = res["control_full_M4"]["all"]["@25"] == 1.0

payload = {
    "arm": "P",
    "idea": "Twin as tensor X[h,r,t]; typed contraction features, no learning",
    "triples": str(TSV.relative_to(REPO)),
    "split": {"seed": 31, "keep_train": 33, "test": 135,
              "rule": "documents_file rows in file order, default_rng(31).permutation, first 33 train"},
    "candidates": len(cands),
    "queries": {"all": n_sub["all"], "test": n_sub["test"], "train": n_sub["train"]},
    "chance@10": round(10 / len(cands), 4),
    "leak_audit": {**leak, "note": "all must be 0; links_to encodes no documents_file pair"},
    "control_full_M4": {"expect": "R@25 == 1.0 by construction (max 17 targets/page)",
                        "passed": control_ok, "results": res["control_full_M4"]["all"]},
    "scoring1_f1_contraction": res["s1_f1"],
    "scoring2_sum_norm": res["s2_sum_norm"],
    "best_feature_ranking_for_rrf": best_feature,
    "scoring3_rrf_best_bm25": res[f"rrf_{'s1' if best_feature == 's1_f1' else 's2'}_bm25"],
    "diagnostics_single_features": {m: res[m] for m in ("f1_only", "f2_only", "f3_only", "f4_only")},
    "rrf_both_variants": {"rrf_s1_bm25": res["rrf_s1_bm25"], "rrf_s2_bm25": res["rrf_s2_bm25"]},
    "bm25_measured": res["bm25"],
    "references": {"bm25@10_168": 0.482, "bm25@10_135": 0.474, "doc_neighbour@10_168": 0.333,
                   "rrf_bm25_struct@10_168": 0.601, "chance@10": 0.0243},
    "notes": [
        "no learning: every number is a typed path count over the Twin minus the 135 held-out edges",
        "s2 = per-query max-normalised sum of log1p(f1..f4); f2 is query-independent popularity",
        "RRF k=60, tie-break alphabetical, candidates identical to BM25 (the 411 source files)",
        "best_feature_ranking_for_rrf chosen by R@10 on all 168 (post-hoc selection between two variants; both variants reported)",
    ],
}

OUT.mkdir(parents=True, exist_ok=True)
out_path = OUT / "arm_p.json"
out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")

print(f"queries all/test/train = {n_sub['all']}/{n_sub['test']}/{n_sub['train']}  "
      f"candidates={len(cands)}  chance@10={payload['chance@10']}")
for m in methods:
    row = res[m]["all"]
    trow = res[m]["test"]
    print(f"  {m:16s} all " + " ".join(f"R@{k}={row[f'@{k}']:.3f}" for k in KS)
          + f"   test@10={trow['@10']:.3f}")
print(f"control passed: {control_ok}   best feature for RRF: {best_feature}")
print(f"wrote {out_path}")
