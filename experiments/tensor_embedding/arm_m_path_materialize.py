"""Arm M: path materialization -- compile the 2-3 hop chain into direct edges.

Diagnosis from Arm J: the connection page -> concept -> code symbol -> module is
2-3 hops long and a bilinear model does not walk paths. Here the composition is
materialized as direct edges, then the Arm J protocol is repeated unchanged:

  (a) doc --mentions--> concept, concept --documents--> symbol
      =>  doc --discusses_symbol--> symbol
  (b) every code symbol carries its module path in its ID
      (code:func:REL#name -> code:module:REL)
      =>  symbol --in_module--> module
  (c) the composition of (a) and (b)
      =>  doc --discusses_module--> module   (direct!)

Leak discipline: the derivations read ONLY mentions/documents edges and entity
IDs -- never a ``documents_file`` edge -- so the 135 held-out test edges cannot
enter any derivation. The 33 kept ``documents_file`` edges stay in training as
in Arm J.

Candidate symmetry (mandatory): scoring runs over exactly the code:module:
nodes whose path is a real source file per bench_crossplane.collect() -- the
same 411 candidates BM25 ranks -- not all ~742 module nodes (Arm J's mistake).

Free baseline without learning: rank candidates by discusses_module chain
count (how often does THIS page discuss symbols of THIS module). That is the
pure contraction count and the honest competitor of the learned model on the
same materialized graph.
"""
from __future__ import annotations
import collections, json, pathlib, sys, time
import numpy as np, torch

T0 = time.time()
from pykeen.pipeline import pipeline
from pykeen.triples import TriplesFactory

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench_crossplane as B


class _LinkFilter:
    """Drop URL hrefs (``//host/...``, ``scheme://``) before collect() resolves
    them: Windows treats ``//host`` as a UNC path and touches the network
    (WinError 64 today). Such hrefs can never match a source file, so the
    (sources, pairs) result is unchanged; sub() is untouched."""

    def __init__(self, orig):
        self._orig = orig

    def findall(self, text):
        return [(label, href) for label, href in self._orig.findall(text)
                if not href.startswith("//") and "://" not in href]

    def sub(self, *args, **kwargs):
        return self._orig.sub(*args, **kwargs)


B.MD_LINK = _LinkFilter(B.MD_LINK)

REPO = pathlib.Path(__file__).resolve().parents[2]
IN = REPO / "runs" / "tensor_embedding_v3"
OUT = REPO / "runs" / "tensor_embedding_v4"
TAG = sys.argv[1] if len(sys.argv) > 1 else "tct_after2"
ROOT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else r"C:/Users/nukei/Desktop/project_tct").resolve()
DIM, EPOCHS = 64, 40
KS = (1, 5, 10, 25)

# --- split: byte-identical to Arm J ------------------------------------
rows = [l.split("\t") for l in (IN / f"triples_{TAG}.tsv").read_text(encoding="utf-8").splitlines()]
doc_edges = [(h, r, t) for h, r, t in rows if r == "documents_file"]
other = [(h, r, t) for h, r, t in rows if r != "documents_file"]
rng = np.random.default_rng(31)
perm = rng.permutation(len(doc_edges))
keep = [doc_edges[i] for i in perm[: max(1, int(0.2 * len(doc_edges)))]]
test = [doc_edges[i] for i in perm[max(1, int(0.2 * len(doc_edges))):]]
base_train = other + keep
print(f"documents_file: {len(doc_edges)} gesamt -> {len(keep)} im Training, {len(test)} zurueckgehalten")

base_ents = {n for h, _, t in base_train for n in (h, t)}
test = [x for x in test if x[0] in base_ents and x[2] in base_ents]
print(f"auswertbar: {len(test)}")

# --- materialization (from training-side edges only) -------------------
def module_of(node: str) -> str | None:
    body = node.split(":", 2)[2] if node.count(":") >= 2 else ""
    if "#" in body:
        return "code:module:" + body.split("#", 1)[0]
    return None

mentions = [(h, t) for h, r, t in other if r == "mentions"]
documents = [(h, t) for h, r, t in other if r == "documents"]
concept_to_syms: dict[str, set[str]] = collections.defaultdict(set)
for c, s in documents:
    concept_to_syms[c].add(s)

discusses_symbol: set[tuple[str, str]] = set()
dm_count: collections.Counter = collections.Counter()   # (doc, module) -> chain count
for d, c in mentions:
    for s in concept_to_syms.get(c, ()):
        discusses_symbol.add((d, s))
        m = module_of(s)
        if m:
            dm_count[(d, m)] += 1

all_symbols = {n for h, _, t in (other + keep) for n in (h, t) if "#" in n}
in_module = {(s, module_of(s)) for s in all_symbols if module_of(s)}

mat = ([(d, "discusses_symbol", s) for d, s in sorted(discusses_symbol)]
       + [(s, "in_module", m) for s, m in sorted(in_module)]
       + [(d, "discusses_module", m) for d, m in sorted(dm_count)])
train = base_train + mat
print(f"materialisiert: discusses_symbol={len(discusses_symbol)}  "
      f"in_module={len(in_module)}  discusses_module={len(dm_count)}  "
      f"train gesamt={len(train)}")

# --- self-checks (constructions that must be 0 / 1) --------------------
train_set = set(train)
leak = sum((h, "documents_file", t) in train_set for h, _, t in test)
assert leak == 0, f"LEAK: {leak} held-out edges in training"
assert not (set(keep) & set(map(tuple, test))), "keep/test overlap"

sources, pairs = B.collect(ROOT)
assert len(sources) == 411 and len(pairs) == 168, \
    f"collect() drifted: {len(sources)} sources, {len(pairs)} pairs (want 411/168)"
candidates = sorted("code:module:" + rel for rel in sources)
assert len(candidates) == len(sources)
cand_set = set(candidates)
tails_outside = [t for _, _, t in test if t not in cand_set]
assert not tails_outside, f"test tails outside candidate set: {tails_outside[:5]}"

def rank_of(ordering: list[str], target: str) -> int:
    return ordering.index(target)

def count_rank(doc: str, counts) -> list[str]:
    return sorted(candidates, key=lambda m: (-counts.get((doc, m), 0), m))

# oracle control: injecting the target as the only counted module must give R@1=1
oracle_ok = all(rank_of(count_rank(h, {(h, t): 1}), t) == 0 for h, _, t in test)
assert oracle_ok, "oracle control failed: ranking bookkeeping is broken"

# --- learned model on the materialized graph ---------------------------
print(f"[phase] checks done, building factory  t+{time.time()-T0:.0f}s")
tf = TriplesFactory.from_labeled_triples(np.array(train, dtype=str))
small = TriplesFactory.from_labeled_triples(np.array(train[:50], dtype=str),
                                            entity_to_id=tf.entity_to_id,
                                            relation_to_id=tf.relation_to_id)
ckpt_dir = pathlib.Path(__file__).resolve().parent / ".arm_m_ckpt"
ckpt_dir.mkdir(exist_ok=True)
res = pipeline(training=tf, testing=small, model="ComplEx",
               model_kwargs=dict(embedding_dim=DIM),
               training_kwargs=dict(num_epochs=EPOCHS, use_tqdm=False, use_tqdm_batch=False,
                                    # persistence only, so a killed run resumes at the last
                                    # epoch instead of restarting; math/seed/epochs unchanged
                                    checkpoint_name="arm_m_complex.pt",
                                    checkpoint_directory=str(ckpt_dir),
                                    checkpoint_frequency=2),
               evaluation_kwargs=dict(use_tqdm=False), random_seed=17, device="cpu")
model, e2id, r2id = res.model, tf.entity_to_id, tf.relation_to_id
print(f"[phase] training done  t+{time.time()-T0:.0f}s")

missing = [m for m in candidates if m not in e2id]
scored_cands = [m for m in candidates if m in e2id]
cand_ids = np.array([e2id[m] for m in scored_cands])
cand_arr = np.array(scored_cands)
rel = r2id["documents_file"]

hits = {k: 0 for k in KS}
for head, _, tail in test:
    hr = torch.tensor([[e2id[head], rel]], dtype=torch.long)
    s = model.score_t(hr).detach().numpy().ravel()[cand_ids]
    order = list(cand_arr[np.argsort(-s)]) + missing   # unembeddable candidates rank last
    r = rank_of(order, tail)
    for k in KS:
        hits[k] += r < k

# --- free baseline: contraction count, no learning ---------------------
cnt_hits = {k: 0 for k in KS}
for head, _, tail in test:
    r = rank_of(count_rank(head, dm_count), tail)
    for k in KS:
        cnt_hits[k] += r < k

# --- same questions, BM25 on the same 411 candidates -------------------
bm = B.BM25(sources)
wanted = {(h.split("knowledge:doc:")[-1], t.split("code:module:")[-1]) for h, _, t in test}
bm_hits = {k: 0 for k in KS}
n_lex = 0
for pair in pairs:
    if (pair["page"], pair["target"]) not in wanted:
        continue
    n_lex += 1
    hit = B.recall_at(bm.rank(pair["query"].split()), pair["target"], KS)
    for k in KS:
        bm_hits[k] += hit[k]

n = len(test)
out = {"arm": "M", "task": "wiki page -> source file it documents (materialized paths)",
       "graph": f"triples_{TAG}.tsv + discusses_symbol/in_module/discusses_module (train-derived only)",
       "tensor_queries": n, "lexical_queries": n_lex, "candidates": len(candidates),
       "candidates_without_embedding": len(missing),
       "model": "ComplEx", "dim": DIM, "epochs": EPOCHS, "random_seed": 17, "split_seed": 31,
       "train_triples": len(train),
       "materialized": {"discusses_symbol": len(discusses_symbol),
                        "in_module": len(in_module),
                        "discusses_module": len(dm_count)},
       "chance@10": round(10 / len(candidates), 5),
       "runtime_seconds": round(time.time() - T0, 1),
       "controls": {"held_out_edges_in_training": leak,
                    "oracle_rank_control_R@1": 1.0 if oracle_ok else 0.0},
       "tensor_materialized": {f"@{k}": round(hits[k] / n, 4) for k in KS},
       "count_baseline": {f"@{k}": round(cnt_hits[k] / n, 4) for k in KS},
       "bm25": {f"@{k}": round(bm_hits[k] / max(1, n_lex), 4) for k in KS}}
print()
for name in ("count_baseline", "bm25", "tensor_materialized"):
    print(f"  {name:20s} " + "  ".join(f"R@{k}={out[name][f'@{k}']:.3f}" for k in KS))
print(f"  Zufall@10 = {out['chance@10']}")
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "arm_m.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT/'arm_m.json'}")
