"""Arm J: the tensor space against BM25 and grep, on identical questions.

Task: a wiki page links to the source file it describes. Hold the link out and
ask each method to name the file.

Fairness, both directions:

* The holdout is an EDGE, not a node. Every target module keeps its hundreds of
  code-plane edges, so the task is transductive. Getting this wrong is what made
  arms E and F unanswerable.
* 20% of the ``documents_file`` edges stay in training, so the model has seen
  the relation it is asked about. The first draft held out all of them and made
  the model guess through ``mentions`` -- a handicap, not a measurement.
* BM25 and grep are scored on exactly the held-out pairs, not on the full set,
  so all three answer the same questions.
"""
from __future__ import annotations
import json, pathlib, sys
import numpy as np, torch
from pykeen.pipeline import pipeline
from pykeen.triples import TriplesFactory

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench_crossplane as B

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "runs" / "tensor_embedding_v3"
TAG = sys.argv[1] if len(sys.argv) > 1 else "tct_after2"
ROOT = pathlib.Path(sys.argv[2]).resolve()
DIM, EPOCHS = 64, 40

rows = [l.split("\t") for l in (OUT / f"triples_{TAG}.tsv").read_text(encoding="utf-8").splitlines()]
doc_edges = [(h, r, t) for h, r, t in rows if r == "documents_file"]
other = [(h, r, t) for h, r, t in rows if r != "documents_file"]
rng = np.random.default_rng(31)
perm = rng.permutation(len(doc_edges))
keep = [doc_edges[i] for i in perm[: max(1, int(0.2 * len(doc_edges)))]]
test = [doc_edges[i] for i in perm[max(1, int(0.2 * len(doc_edges))):]]
train = other + keep
print(f"documents_file: {len(doc_edges)} gesamt -> {len(keep)} im Training, {len(test)} zurueckgehalten")

ents = {n for h, _, t in train for n in (h, t)}
test = [x for x in test if x[0] in ents and x[2] in ents]
print(f"auswertbar: {len(test)}")

tf = TriplesFactory.from_labeled_triples(np.array(train, dtype=str))
small = TriplesFactory.from_labeled_triples(np.array(train[:50], dtype=str),
                                            entity_to_id=tf.entity_to_id,
                                            relation_to_id=tf.relation_to_id)
res = pipeline(training=tf, testing=small, model="ComplEx",
               model_kwargs=dict(embedding_dim=DIM),
               training_kwargs=dict(num_epochs=EPOCHS, use_tqdm=False, use_tqdm_batch=False),
               evaluation_kwargs=dict(use_tqdm=False), random_seed=17, device="cpu")
model, e2id, r2id = res.model, tf.entity_to_id, tf.relation_to_id
modules = sorted(n for n in ents if n.startswith("code:module:"))
mod_ids = np.array([e2id[m] for m in modules])
mod_arr = np.array(modules)
rel = r2id["documents_file"]

KS = (1, 5, 10, 25)
hits = {k: 0 for k in KS}
for head, _, tail in test:
    hr = torch.tensor([[e2id[head], rel]], dtype=torch.long)
    s = model.score_t(hr).detach().numpy().ravel()[mod_ids]
    rank = int(np.where(mod_arr[np.argsort(-s)] == tail)[0][0])
    for k in KS:
        hits[k] += rank < k

# --- same questions, lexical methods -----------------------------------
sources, pairs = B.collect(ROOT)
bm = B.BM25(sources)
wanted = {(h.split("knowledge:doc:")[-1], t.split("code:module:")[-1]) for h, _, t in test}
lex = {m: {k: 0 for k in KS} for m in ("exact_token", "bm25")}
n_lex = 0
for pair in pairs:
    if (pair["page"], pair["target"]) not in wanted:
        continue
    n_lex += 1
    q = pair["query"].split()
    for m, ranking in (("exact_token", B.exact_token_rank(q, sources)), ("bm25", bm.rank(q))):
        hit = B.recall_at(ranking, pair["target"], KS)
        for k in KS:
            lex[m][k] += hit[k]

n = len(test)
out = {"arm": "J", "task": "wiki page -> source file it documents",
       "tensor_queries": n, "lexical_queries": n_lex, "candidates": len(modules),
       "model": "ComplEx", "dim": DIM, "epochs": EPOCHS,
       "chance@10": round(10 / len(modules), 5),
       "tensor": {f"@{k}": round(hits[k] / n, 4) for k in KS},
       "bm25": {f"@{k}": round(lex["bm25"][k] / max(1, n_lex), 4) for k in KS},
       "exact_token": {f"@{k}": round(lex["exact_token"][k] / max(1, n_lex), 4) for k in KS}}
print()
for name in ("exact_token", "bm25", "tensor"):
    print(f"  {name:12s} " + "  ".join(f"R@{k}={out[name][f'@{k}']:.3f}" for k in KS))
print(f"  Zufall@10 = {out['chance@10']}")
(OUT / "arm_j.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT/'arm_j.json'}")
