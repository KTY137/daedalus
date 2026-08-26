"""Arm K: does the Twin's STRUCTURE add anything to BM25 -- without learning?

Arm J settled the learned question: ComplEx reaches R@10 = 0.022 where BM25
reaches 0.474, on identical queries. A trained model loses to a method with no
training at all, and to grep.

But `doc_neighbour` -- pure deterministic structure, also untrained -- reached
0.333. So structure carries signal; learning over it does not. This arm asks the
only question left that could make the Twin pay: does fusing the two beat BM25
alone? Reciprocal rank fusion, no parameters, no training, no tuning.

If it does not, the honest answer for retrieval is BM25, and the Twin's value
lies elsewhere -- in the verifier and the deterministic brief, both of which
found real defects today.
"""
from __future__ import annotations
import collections, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench_crossplane as B

ROOT = pathlib.Path(sys.argv[1]).resolve()
OUT = pathlib.Path(__file__).resolve().parents[2] / "runs" / "tensor_embedding_v3"
KS = (1, 5, 10, 25)
K_RRF = 60.0

sources, pairs = B.collect(ROOT)
bm = B.BM25(sources)
methods = ("exact_token", "bm25", "doc_neighbour", "rrf_bm25_struct")
totals = {m: {k: 0 for k in KS} for m in methods}

for pair in pairs:
    q = pair["query"].split()
    rank_bm = B.bm25 if False else bm.rank(q)
    rank_st = B.doc_neighbour_rank(pair, pairs, sources)
    rank_ex = B.exact_token_rank(q, sources)
    pos_bm = {rel: i for i, rel in enumerate(rank_bm)}
    pos_st = {rel: i for i, rel in enumerate(rank_st)}
    fused = sorted(sources, key=lambda r: -(1.0 / (K_RRF + pos_bm[r]) + 1.0 / (K_RRF + pos_st[r])))
    for name, ranking in (("exact_token", rank_ex), ("bm25", rank_bm),
                          ("doc_neighbour", rank_st), ("rrf_bm25_struct", fused)):
        hit = B.recall_at(ranking, pair["target"], KS)
        for k in KS:
            totals[name][k] += hit[k]

n = len(pairs)
out = {"arm": "K", "queries": n, "candidates": len(sources),
       "fusion": "reciprocal rank fusion, k=60, no training, no tuning",
       "results": {m: {f"@{k}": round(v[k] / n, 4) for k in KS} for m, v in totals.items()},
       "tensor_reference@10": 0.022, "chance@10": round(10 / len(sources), 5)}
print(f"queries={n}  Kandidaten={len(sources)}  Zufall@10={out['chance@10']}")
for m in methods:
    print(f"  {m:18s} " + "  ".join(f"R@{k}={out['results'][m][f'@{k}']:.3f}" for k in KS))
print(f"  {'tensor (Arm J)':18s} R@10=0.022")
(OUT / "arm_k.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT/'arm_k.json'}")
