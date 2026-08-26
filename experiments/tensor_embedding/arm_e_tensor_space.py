"""EXPERIMENT ``tensor-embedding-v3``, Arm E: the fourfold graph in a tensor space.

The model (SPEC §3), one embedding table for every plane and any arity:

    score(kind, n_1..n_a) = sum_r  G[kind, r] * prod_i ( E[n_i, r] * R[role_i, r] )

Retrieval is a contraction: hold some slots, multiply their modulated vectors
elementwise, and one matrix product against ``E`` scores every candidate for the
missing slot.

Four models at equal parameter budget: ungrained character trigrams (the winner
of v1 and v2), exact name match, the same learned form restricted to today's
hub-routed binary pairs, and the full n-ary form.

The control that decides whether any of it means anything is ``scramble``:
names are replaced by random tokens carrying no signal, so only structure is
left. A tensor that only wins with readable names has learned trigrams, not
structure (SPEC §5, K11).

Run:  python experiments/tensor_embedding/arm_e_tensor_space.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hrr import TRIGRAM_BOOK_SIZE, normalise  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "runs" / "tensor_embedding_v3"

# Shape parameters MEASURED in Arm D on the real fixture.
ROLES = ("type_field", "data_column", "schema_property", "doc_mention", "code_use")
ROLE_PLANE = {
    "type_field": "type", "data_column": "data", "schema_property": "data",
    "doc_mention": "knowledge", "code_use": "code",
}
HUB_ROLE = "type_field"                    # what today's schema privileges
BINARY_REACHABLE = {"type_field", "data_column", "schema_property"}
ARITY_CHOICES = (4, 5)
CONTAINER_SIZE = 6
MAX_CONTEXT = 3

N_CONCEPTS = 400
RANK = 48
EPOCHS = 40
LR = 0.05
NEG = 24
SYLLABLES = ["ka", "ro", "mi", "tan", "vel", "sur", "pex", "dol", "nim", "bra", "quo", "zel"]


def unique_names(rng: np.random.Generator, n: int) -> list[str]:
    seen: dict[str, None] = {}
    while len(seen) < n:
        seen["".join(SYLLABLES[i] for i in rng.integers(0, len(SYLLABLES), size=3))] = None
    return list(seen)


def drift(name: str, mode: str, rng: np.random.Generator) -> str:
    """Name drift between planes, as Arm D observed it on the fixture."""
    if mode == "none":
        return name
    roll = rng.random()
    if mode == "mild":
        if roll < 0.4:
            return f"bias_{name}"
        if roll < 0.7:
            return f"{name}_v2"
        return name
    if mode == "scramble":                  # K11: names carry no signal at all
        return "".join(SYLLABLES[i] for i in rng.integers(0, len(SYLLABLES), size=3))
    raise ValueError(mode)


def build_corpus(seed: int, name_mode: str) -> dict:
    """Concepts realised across planes, plus container co-occurrence claims.

    The first draft gave every node exactly ONE claim. Holding out a slot then
    removed the target node from training entirely, so its embedding stayed at
    random init and both learned models scored 0.000 -- not because the tensor
    is weak but because the task was inductive by construction. Character
    trigrams were unaffected: they read the surface name, which needs no
    training.

    That failure is retained as a finding of its own (cold start), and the task
    is made transductive the way a real repository is: a field also participates
    in a container claim with its sibling fields, so holding out one
    realization slot still leaves the node present elsewhere.
    """
    rng = np.random.default_rng(seed)
    bases = unique_names(rng, N_CONCEPTS)
    nodes: list[dict] = []
    claims: list[dict] = []
    container_members: dict[int, list[dict]] = {}
    for c, base in enumerate(bases):
        arity = ARITY_CHOICES[int(rng.integers(0, len(ARITY_CHOICES)))]
        roles = [HUB_ROLE] + list(
            rng.choice([r for r in ROLES if r != HUB_ROLE], size=arity - 1, replace=False)
        )
        slots = []
        for role in roles:
            name = base if role == HUB_ROLE else drift(base, name_mode, rng)
            nodes.append({"concept": c, "role": role, "plane": ROLE_PLANE[role], "name": name})
            slots.append({"role": role, "node": len(nodes) - 1})
        claims.append({"kind": "concept_realization", "concept": c, "slots": slots})
        container_members.setdefault(c // CONTAINER_SIZE, []).extend(slots)

    for container, members in container_members.items():
        if len(members) >= 2:
            claims.append({"kind": "container_cooccurrence", "concept": -1 - container,
                           "slots": members})
    return {"nodes": nodes, "claims": claims}


def trigram_matrix(nodes: list[dict]) -> np.ndarray:
    mat = np.zeros((len(nodes), TRIGRAM_BOOK_SIZE))
    for i, node in enumerate(nodes):
        padded = f"^{node['name'].lower()}$"
        for j in range(max(0, len(padded) - 2)):
            mat[i, zlib.crc32(padded[j : j + 3].encode("utf-8")) % TRIGRAM_BOOK_SIZE] += 1.0
        mat[i] = normalise(mat[i])
    return mat


def make_queries(corpus: dict, rng: np.random.Generator) -> list[dict]:
    """Hold out ONE slot per claim; the rest is the observation."""
    queries = []
    for claim in corpus["claims"]:
        if claim["kind"] != "concept_realization":
            continue
        hidden = int(rng.integers(0, len(claim["slots"])))
        held = claim["slots"][hidden]
        observed = [s for k, s in enumerate(claim["slots"]) if k != hidden]
        queries.append({"observed": observed, "held": held, "concept": claim["concept"]})
    return queries


def train_cp(corpus: dict, queries: list[dict], nary: bool, seed: int) -> tuple:
    """Train the contraction itself: mask one slot, retrieve it from the rest.

    The first draft optimised a margin on the raw multilinear score. At rank 48
    and init scale 0.1 the product over five slots is ~1e-5, so the margin was
    a constant, the gradient was noise, and both learned models scored 0.000 --
    below chance. Two fixes, both of them about conditioning rather than about
    the model:

    * the context product is renormalised to unit length, so arity 2 and arity
      5 live on the same scale and can share one embedding table;
    * the loss is InfoNCE over sampled negatives, which is the retrieval
      operation of SPEC section 3 trained directly instead of a proxy.

    ``nary=False`` trains on hub-routed PAIRS only -- the shape today's schema
    can express -- at identical rank and epochs, so the budgets match.
    """
    rng = np.random.default_rng(seed)
    n_nodes = len(corpus["nodes"])
    emb = rng.normal(0, 1.0 / np.sqrt(RANK), size=(n_nodes, RANK))
    role_mod = np.ones((len(ROLES), RANK)) + rng.normal(0, 0.05, size=(len(ROLES), RANK))
    gate = np.ones(RANK)
    role_index = {r: i for i, r in enumerate(ROLES)}
    held_nodes = {q["held"]["node"] for q in queries}

    items = []
    for claim in corpus["claims"]:
        if claim["kind"] == "concept_realization":
            slots = [s for s in claim["slots"] if s["node"] not in held_nodes]
        else:
            slots = list(claim["slots"])
        if len(slots) < 2:
            continue
        if nary:
            groups = [slots]
        else:
            hub = [s for s in slots if s["role"] == HUB_ROLE]
            groups = [
                [hub[0], other]
                for other in slots
                if hub and other["role"] != HUB_ROLE and other["role"] in BINARY_REACHABLE
            ]
        for group in groups:
            for k in range(len(group)):
                context = group[:k] + group[k + 1 :]
                # Cap the context. An elementwise product over 26 factors of
                # magnitude ~0.14 is ~1e-23; after normalisation that is pure
                # floating-point noise, and it poisoned every gradient in the
                # previous run. A sampled context keeps the product on scale.
                if len(context) > MAX_CONTEXT:
                    pick = rng.choice(len(context), size=MAX_CONTEXT, replace=False)
                    context = [context[i] for i in sorted(pick)]
                items.append((context, group[k]))

    for _ in range(EPOCHS):
        for t in rng.permutation(len(items)):
            context_slots, target = items[t]
            ctx = np.ones(RANK)
            for s in context_slots:
                ctx = ctx * (emb[s["node"]] * role_mod[role_index[s["role"]]])
            ctx = ctx * gate
            norm = np.linalg.norm(ctx) + 1e-12
            ctx = ctx / norm

            r_t = role_mod[role_index[target["role"]]]
            negs = rng.integers(0, n_nodes, size=NEG)
            cand = np.concatenate([[target["node"]], negs])
            logits = (emb[cand] * r_t) @ ctx
            logits -= logits.max()
            probs = np.exp(logits)
            probs /= probs.sum()
            probs[0] -= 1.0                      # dL/dlogit for InfoNCE
            emb[cand] -= LR * probs[:, None] * (ctx * r_t)[None, :]
    return emb, role_mod, gate, role_index


def evaluate(corpus, queries, model, trig, ks=(1, 5, 10)) -> dict:
    """Recall@k of the held-out slot, overall and split by plane group."""
    nodes = corpus["nodes"]
    n = len(nodes)
    hits = {k: 0 for k in ks}
    hits_hidden_plane = {k: 0 for k in ks}
    hidden_plane_total = 0

    if model[0] == "learned":
        _, emb, role_mod, gate, role_index = model
    for q in queries:
        held = q["held"]
        role = held["role"]
        if model[0] == "trigram":
            scores = trig @ trig[q["observed"][0]["node"]]
        elif model[0] == "exact":
            target = nodes[q["observed"][0]["node"]]["name"]
            scores = np.array([1.0 if nodes[i]["name"] == target else 0.0 for i in range(n)])
        else:
            rest = np.ones(RANK)
            for s in q["observed"][:MAX_CONTEXT]:
                rest = rest * (emb[s["node"]] * role_mod[role_index[s["role"]]])
            rest = rest * gate
            rest = rest / (np.linalg.norm(rest) + 1e-12)
            scores = (emb * role_mod[role_index[role]]) @ rest
        scores = scores.copy()
        for s in q["observed"]:
            scores[s["node"]] = -np.inf
        order = np.argsort(-scores)
        rank = int(np.where(order == held["node"])[0][0])
        blind = role not in BINARY_REACHABLE
        if blind:
            hidden_plane_total += 1
        for k in ks:
            if rank < k:
                hits[k] += 1
                if blind:
                    hits_hidden_plane[k] += 1
    return {
        "recall": {f"@{k}": round(hits[k] / len(queries), 4) for k in ks},
        "recall_on_planes_binary_cannot_name": {
            f"@{k}": (round(hits_hidden_plane[k] / hidden_plane_total, 4) if hidden_plane_total else None)
            for k in ks
        },
        "queries": len(queries),
        "queries_on_blind_planes": hidden_plane_total,
    }


def main() -> int:
    started = time.time()
    payload = {
        "experiment": "tensor-embedding-v3",
        "arm": "E",
        "concepts": N_CONCEPTS,
        "rank": RANK,
        "epochs": EPOCHS,
        "arity_choices": list(ARITY_CHOICES),
        "numpy": np.__version__,
        "results": {},
    }
    for name_mode in ("none", "mild", "scramble"):
        corpus = build_corpus(seed=5, name_mode=name_mode)
        queries = make_queries(corpus, np.random.default_rng(6))
        trig = trigram_matrix(corpus["nodes"])
        payload["results"][name_mode] = {}

        for label, model in (
            ("exact", ("exact",)),
            ("trigram", ("trigram",)),
            ("cp_binary", None),
            ("cp_nary", None),
        ):
            if model is None:
                nary = label == "cp_nary"
                emb, role_mod, gate, role_index = train_cp(corpus, queries, nary=nary, seed=9)
                model = ("learned", emb, role_mod, gate, role_index)
            payload["results"][name_mode][label] = evaluate(corpus, queries, model, trig)
            r = payload["results"][name_mode][label]
            print(
                f"{name_mode:9s} {label:10s} R@1={r['recall']['@1']:.3f} "
                f"R@10={r['recall']['@10']:.3f}   blind-plane R@10="
                f"{r['recall_on_planes_binary_cannot_name']['@10']}"
            )
        print()

    payload["elapsed_seconds"] = round(time.time() - started, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arm_e.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {OUT / 'arm_e.json'}  ({payload['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
