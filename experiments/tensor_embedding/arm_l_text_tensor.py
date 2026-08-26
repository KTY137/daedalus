"""Arm L: text-informed tensor (+ Arm O abbreviation regime).

Core bet of v4: the learned tensor lost so far because its embeddings were free
parameters that never saw the TEXT (BM25 reads words). Here every entity vector
is a learned function of the character trigrams of the node's name:

    phi(node) = L2-normalised trigram hash vector (4096 buckets, zlib.crc32,
                padded lowercase word pieces), deterministic
    e(node)   = tanh(W @ phi),  W in R^{128x4096}, shared across ALL nodes
    score(h,r,t) = (e_h * w_r) . e_t          (diagonal relation modulation)

Training: InfoNCE with sampled negatives over ALL training triples (the whole
graph is supervision, not just the 33 kept documents_file edges).

Leakage rule: for knowledge:doc nodes the stem tokens of the node's own file
name are removed from phi (mirror of the bench scrub, which removes target
basenames from the query prose). Both variants are trained and reported; the
scrubbed one is the comparable number.

Eval 1  the 135 held-out documents_file pairs, candidates = exactly the 411
        code:module: nodes whose path is in bench_crossplane.collect().sources.
Eval 2  (Arm O) 200 real underscore symbol names from the twin; query is the
        vowel-stripped form of each word piece (config -> cnfg); candidates are
        the 200 original names. Raw trigram cosine vs learned encoder cosine.

Run:  python experiments/tensor_embedding/arm_l_text_tensor.py
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import time
import zlib

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bench_crossplane as B

REPO = pathlib.Path(__file__).resolve().parents[2]
TRIPLES = REPO / "runs" / "tensor_embedding_v3" / "triples_tct_after2.tsv"
OUT_DIR = REPO / "runs" / "tensor_embedding_v4"
ROOT = pathlib.Path("C:/Users/nukei/Desktop/project_tct")

DIM = 128
BUCKETS = 4096
EPOCHS = 24
BATCH = 4536  # 8 mega-steps per epoch: this box pays per-op, not per-FLOP
NEGS = 128
LR = 3e-3
SEED_TORCH = 17
SEED_SPLIT = 31
KS = (1, 5, 10, 25)

# ---------------------------------------------------------------- names / phi

def node_name_tokens(node_id: str) -> list[str]:
    """Lowercased word pieces of the node's name.

    - code:module    -> file path stem plus directory parts (dotted external
                        module names are used whole)
    - knowledge:doc  -> file path stem plus directory parts (same treatment;
                        the ID is a file path, and the scrub must leave the
                        directory context behind)
    - knowledge:concept -> the concept string
    - everything else -> last path/symbol component (part after '#' if any,
                        else last '/'-component)
    """
    kind, sub, ident = node_id.split(":", 2)
    prefix = f"{kind}:{sub}"
    if prefix == "code:module":
        text = ident[:-3] if ident.endswith(".py") else ident
    elif prefix == "knowledge:doc":
        text = ident.rsplit(".", 1)[0] if "." in ident.rsplit("/", 1)[-1] else ident
    elif prefix == "knowledge:concept":
        text = ident
    else:
        text = ident.split("#", 1)[1] if "#" in ident else ident.rsplit("/", 1)[-1]
    return B.split_identifier(text)


def doc_own_stem_pieces(node_id: str) -> set[str]:
    ident = node_id.split(":", 2)[2]
    stem = pathlib.Path(ident).stem
    return set(B.split_identifier(stem))


def trigram_counts(tokens: list[str]) -> dict[int, float]:
    counts: dict[int, float] = {}
    for tok in tokens:
        s = "#" + tok.lower() + "#"
        for i in range(len(s) - 2):
            b = zlib.crc32(s[i : i + 3].encode("utf-8")) % BUCKETS
            counts[b] = counts.get(b, 0.0) + 1.0
    return counts


def phi_dense(tokens: list[str]) -> np.ndarray:
    v = np.zeros(BUCKETS, dtype=np.float32)
    for b, c in trigram_counts(tokens).items():
        v[b] += c
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def entity_tokens(ent: str, scrub_docs: bool) -> list[str]:
    toks = node_name_tokens(ent)
    if scrub_docs and ent.startswith("knowledge:doc:"):
        drop = doc_own_stem_pieces(ent)
        toks = [t for t in toks if t not in drop]
    return toks


def build_phi_sparse(entities: list[str], scrub_docs: bool):
    """Padded (bucket-index, weight) rows; weight rows are L2-normalised.

    Pad entries use bucket 0 with weight 0, so they contribute nothing to the
    gather-sum and nothing to the gradient.
    """
    per_ent = []
    for ent in entities:
        counts = trigram_counts(entity_tokens(ent, scrub_docs))
        items = sorted(counts.items())
        norm = math.sqrt(sum(c * c for _, c in items)) or 1.0
        per_ent.append([(b, c / norm) for b, c in items])
    lmax = max(1, max(len(x) for x in per_ent))
    idx = np.zeros((len(entities), lmax), dtype=np.int64)
    val = np.zeros((len(entities), lmax), dtype=np.float32)
    for i, items in enumerate(per_ent):
        for j, (b, w) in enumerate(items):
            idx[i, j], val[i, j] = b, w
    return torch.from_numpy(idx), torch.from_numpy(val), lmax


# ------------------------------------------------------------------- training

def train_model(train: list[tuple[str, str, str]], scrub_docs: bool):
    entities = sorted({n for h, _, t in train for n in (h, t)})
    relations = sorted({r for _, r, _ in train})
    e2id = {e: i for i, e in enumerate(entities)}
    r2id = {r: i for i, r in enumerate(relations)}
    phi_idx, phi_val, lmax = build_phi_sparse(entities, scrub_docs)

    torch.manual_seed(SEED_TORCH)
    W = torch.nn.Parameter(torch.randn(BUCKETS, DIM) * 0.1)  # stored transposed
    Wrel = torch.nn.Parameter(torch.ones(len(relations), DIM))
    opt = torch.optim.Adam([W, Wrel], lr=LR)

    h_idx = torch.tensor([e2id[h] for h, _, _ in train], dtype=torch.long)
    r_idx = torch.tensor([r2id[r] for _, r, _ in train], dtype=torch.long)
    t_idx = torch.tensor([e2id[t] for _, _, t in train], dtype=torch.long)
    n_tr = len(train)
    n_ent = len(entities)
    rng = np.random.default_rng(SEED_TORCH)
    t_start = time.time()

    losses = []
    for epoch in range(EPOCHS):
        order = torch.from_numpy(rng.permutation(n_tr))
        total = 0.0
        for s in range(0, n_tr, BATCH):
            b = order[s : s + BATCH]
            nb = len(b)
            neg = torch.from_numpy(rng.integers(0, n_ent, NEGS))
            # one fused sparse gather-sum for heads, tails, and negatives:
            # e = tanh(W.T @ phi) row-wise
            all_idx = torch.cat([h_idx[b], t_idx[b], neg])
            e_all = torch.tanh(F.embedding_bag(
                phi_idx[all_idx], W, per_sample_weights=phi_val[all_idx],
                mode="sum"))
            e_h, e_t, e_n = e_all[:nb], e_all[nb : 2 * nb], e_all[2 * nb :]
            wr = Wrel[r_idx[b]]
            pos = ((e_h * wr) * e_t).sum(-1, keepdim=True)
            # both-side corruption, one stacked cross-entropy
            logits = torch.cat([
                torch.cat([pos, (e_h * wr) @ e_n.T], dim=1),
                torch.cat([pos, (e_t * wr) @ e_n.T], dim=1)], dim=0)
            tgt = torch.zeros(2 * nb, dtype=torch.long)
            loss = F.cross_entropy(logits, tgt)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.detach()) * nb
        losses.append(round(total / n_tr, 4))
        if epoch % 5 == 0 or epoch == EPOCHS - 1:
            print(f"    [{'scrub' if scrub_docs else 'plain'}] epoch {epoch:3d} "
                  f"loss {losses[-1]}  (lmax={lmax}, t={time.time()-t_start:.0f}s)",
                  flush=True)
    return {"W": W.detach(), "Wrel": Wrel.detach(), "e2id": e2id, "r2id": r2id,
            "entities": entities, "scrub": scrub_docs, "losses": losses}


def encode_tokens(model, tokens: list[str]) -> torch.Tensor:
    v = torch.from_numpy(phi_dense(tokens))
    return torch.tanh(v @ model["W"])


# --------------------------------------------------------------------- eval 1

def eval_pairs(model, test, cand_ids: list[str]) -> dict:
    W, Wrel = model["W"], model["Wrel"]
    wr = Wrel[model["r2id"]["documents_file"]]
    cand_vecs = []
    for cid in cand_ids:
        toks = node_name_tokens(cid)
        cand_vecs.append(torch.tanh(torch.from_numpy(phi_dense(toks)) @ W))
    C = torch.stack(cand_vecs)  # [411, DIM]
    pos = {c: i for i, c in enumerate(cand_ids)}
    hits = {k: 0 for k in KS}
    ranks = []
    for head, _, tail in test:
        toks = node_name_tokens(head)
        if model["scrub"]:
            drop = doc_own_stem_pieces(head)
            toks = [t for t in toks if t not in drop]
        e_h = torch.tanh(torch.from_numpy(phi_dense(toks)) @ W)
        scores = (C @ (e_h * wr)).numpy()
        order = np.argsort(-scores, kind="stable")
        rank = int(np.where(order == pos[tail])[0][0])
        ranks.append(rank)
        for k in KS:
            hits[k] += rank < k
    n = len(test)
    return {f"@{k}": round(hits[k] / n, 4) for k in KS} | {
        "mean_rank": round(float(np.mean(ranks)) + 1, 1)}


# ----------------------------------------------------------- eval 2 / arm O

def strip_vowels(piece: str) -> str:
    out = "".join(ch for ch in piece if ch not in "aeiou")
    return out if out else piece[:1]


def rank_recall(qvecs: torch.Tensor, cvecs: torch.Tensor) -> dict:
    """qvecs[i] should retrieve cvecs[i]; cosine ranking over all candidates."""
    q = F.normalize(qvecs, dim=1)
    c = F.normalize(cvecs, dim=1)
    scores = q @ c.T
    n = len(q)
    hits = {k: 0 for k in KS}
    for i in range(n):
        order = np.argsort(-scores[i].numpy(), kind="stable")
        rank = int(np.where(order == i)[0][0])
        for k in KS:
            hits[k] += rank < k
    return {f"@{k}": round(hits[k] / n, 4) for k in KS}


def arm_o(all_rows, models) -> dict:
    syms = set()
    for h, _, t in all_rows:
        for node in (h, t):
            if node.startswith(("type:field:", "code:func:")):
                ident = node.split(":", 2)[2]
                sym = ident.split("#", 1)[-1].split(".")[-1]
                if "_" in sym.strip("_") and len(sym) >= 4:
                    syms.add(sym)
    syms = sorted(syms)
    rng = np.random.default_rng(SEED_SPLIT)
    names = [syms[i] for i in rng.choice(len(syms), 200, replace=False)]
    queries = ["_".join(strip_vowels(p) for p in n.split("_") if p) for n in names]

    def phi_stack(strings):
        return torch.stack([torch.from_numpy(phi_dense(B.split_identifier(s)))
                            for s in strings])

    phi_names, phi_q = phi_stack(names), phi_stack(queries)
    out = {"n": 200, "pool_size": len(syms), "chance@10": round(10 / 200, 4),
           "example": {"name": names[0], "query": queries[0]},
           "trigram_cosine": rank_recall(phi_q, phi_names),
           "control_identity_trigram": rank_recall(phi_names, phi_names)}
    for tag, model in models.items():
        W = model["W"]
        e_names = torch.tanh(phi_names @ W)
        e_q = torch.tanh(phi_q @ W)
        out[f"encoder_cosine_{tag}"] = rank_recall(e_q, e_names)
    return out


# ----------------------------------------------------------------------- main

def main() -> int:
    t0 = time.time()
    rows = [tuple(l.split("\t")) for l in
            TRIPLES.read_text(encoding="utf-8").splitlines()]
    doc_edges = [t for t in rows if t[1] == "documents_file"]
    other = [t for t in rows if t[1] != "documents_file"]
    rng = np.random.default_rng(SEED_SPLIT)
    perm = rng.permutation(len(doc_edges))
    n_keep = max(1, int(0.2 * len(doc_edges)))
    keep = [doc_edges[i] for i in perm[:n_keep]]
    test = [doc_edges[i] for i in perm[n_keep:]]
    train = other + keep
    ents = {n for h, _, t in train for n in (h, t)}
    test = [x for x in test if x[0] in ents and x[2] in ents]
    print(f"documents_file: {len(doc_edges)} total -> {len(keep)} train, "
          f"{len(test)} test after entity filter")

    # self-check 1: no held-out edge anywhere in training
    leak = set(test) & set(train)
    assert not leak, f"held-out edges leaked into training: {len(leak)}"

    # candidate symmetry: exactly the modules whose path is a bench source file.
    # Scoped monkeypatch: absolute markdown links like //host/... become UNC
    # paths on Windows and Path.resolve() then touches the network (transient
    # WinError 64). Pre-empt UNC resolution; relative_to(root) still raises
    # ValueError for them, so collect() skips them exactly as on POSIX.
    _orig_resolve = pathlib.Path.resolve

    def _safe_resolve(self, strict=False):
        a = os.path.abspath(self)
        if a.startswith("\\\\"):
            return pathlib.Path(a)
        try:
            return _orig_resolve(self, strict)
        except OSError:
            return pathlib.Path(a)

    cache = pathlib.Path(
        "C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/"
        "1c63cfa2-20c9-445a-a8cd-225438046633/scratchpad/arm_l_collect_cache.json")
    pathlib.Path.resolve = _safe_resolve
    try:
        if cache.exists():
            blob = json.loads(cache.read_text(encoding="utf-8"))
            sources, pairs = blob["sources"], blob["pairs"]
            print(f"collect(): loaded from cache {cache.name}")
        else:
            sources, pairs = B.collect(ROOT)
            cache.write_text(json.dumps({"sources": sources, "pairs": pairs}),
                             encoding="utf-8")
    finally:
        pathlib.Path.resolve = _orig_resolve
    cand_ids = ["code:module:" + rel for rel in sorted(sources)]
    missing = [t for _, _, t in test if t not in set(cand_ids)]
    assert not missing, f"test tails outside candidate set: {missing[:5]}"
    print(f"candidates: {len(cand_ids)} (bench sources: {len(sources)})")

    # BM25 / exact_token recomputed on the identical 135 questions
    bm = B.BM25(sources)
    wanted = {(h.split("knowledge:doc:")[-1], t.split("code:module:")[-1])
              for h, _, t in test}
    lex = {m: {k: 0 for k in KS} for m in ("exact_token", "bm25")}
    n_lex = 0
    for pair in pairs:
        if (pair["page"], pair["target"]) not in wanted:
            continue
        n_lex += 1
        q = pair["query"].split()
        for m, ranking in (("exact_token", B.exact_token_rank(q, sources)),
                           ("bm25", bm.rank(q))):
            hit = B.recall_at(ranking, pair["target"], KS)
            for k in KS:
                lex[m][k] += hit[k]
    lex_out = {m: {f"@{k}": round(v[k] / max(1, n_lex), 4) for k in KS}
               for m, v in lex.items()}
    print(f"lexical baselines recomputed on {n_lex} of {len(test)} questions")

    models = {}
    for tag, scrub in (("scrubbed", True), ("unscrubbed", False)):
        t1 = time.time()
        models[tag] = train_model(train, scrub)
        print(f"trained {tag}: loss {models[tag]['losses'][0]} -> "
              f"{models[tag]['losses'][-1]}  ({time.time()-t1:.0f}s)")

    eval1 = {tag: eval_pairs(m, test, cand_ids) for tag, m in models.items()}
    for tag, row in eval1.items():
        print(f"  eval1 {tag:10s} " +
              "  ".join(f"R@{k}={row[f'@{k}']}" for k in KS))

    o = arm_o(rows, models)
    print(f"  armO trigram   R@10={o['trigram_cosine']['@10']}   "
          f"encoder(scrubbed) R@10={o['encoder_cosine_scrubbed']['@10']}   "
          f"identity-control R@1={o['control_identity_trigram']['@1']}")

    enc10 = o["encoder_cosine_scrubbed"]["@10"]
    tri10 = o["trigram_cosine"]["@10"]
    win_c = bool(enc10 >= 3 * tri10 and enc10 >= 0.15)

    out = {
        "arm": "L (text-informed tensor) + O (abbreviation regime)",
        "graph": str(TRIPLES.relative_to(REPO)).replace("\\", "/"),
        "model": {"phi": "char-trigram hash, 4096 buckets, zlib.crc32 on "
                          "'#'-padded lowercase word pieces, L2-normalised",
                  "encoder": "e = tanh(W @ phi), W shared 128x4096",
                  "score": "(e_h * w_r) . e_t, diagonal w_r per relation",
                  "loss": f"InfoNCE, {NEGS} shared uniform negatives, "
                          "both-side corruption, over ALL training triples",
                  "negatives": NEGS,
                  "dim": DIM, "epochs": EPOCHS, "batch": BATCH, "lr": LR,
                  "seeds": {"split": SEED_SPLIT, "torch": SEED_TORCH}},
        "split": {"documents_file_total": len(doc_edges), "train_kept": len(keep),
                  "test": len(test), "train_triples": len(train)},
        "candidates": len(cand_ids),
        "chance@10": round(10 / len(cand_ids), 4),
        "doc_scrub": "knowledge:doc phi drops the word pieces of the node's own "
                      "file stem; all 37 head pages live in docs/wiki/, so the "
                      "scrubbed head text is the same for every page "
                      "('docs wiki') and scrubbed eval1 is a popularity prior "
                      "by construction",
        "eval1_documents_file_135": {
            "tensor": eval1,
            "bm25": lex_out["bm25"],
            "exact_token": lex_out["exact_token"],
            "lexical_queries": n_lex,
        },
        "eval2_arm_o": o,
        "win_condition_c": {"encoder>=3x_trigram_and_R10>=0.15": win_c,
                            "encoder@10": enc10, "trigram@10": tri10},
        "training_loss_first_last": {t: [m["losses"][0], m["losses"][-1]]
                                     for t, m in models.items()},
        "self_checks": {
            "no_test_edge_in_train": len(leak) == 0,
            "all_test_tails_in_candidates": len(missing) == 0,
            "candidates_equal_bench_sources": len(cand_ids) == len(sources),
            "identity_control_trigram_R@1": o["control_identity_trigram"]["@1"],
        },
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "arm_l.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8",
                    newline="\n")
    print(f"wrote {path}  ({out['runtime_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
