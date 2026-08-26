"""EXPERIMENT ``tensor-embedding-v3``, Arm F: the same question, trusted code.

Arm E asked whether a learned tensor space beats ungrained character similarity
for cross-plane retrieval, and could not answer it: four hand-rolled trainers,
none above chance, while an oracle showed R@10 = 1.000 was available. A later
check settled the cause -- the trainer memorises fine (TRAIN R@1 0.83-0.95 at
arity 3), so it was never an optimiser bug. The task was: the holdout removed
the ONLY concept-identifying edge, leaving container co-occurrence that does
not determine the concept.

Arm F fixes both problems at once.

* The implementation is PyKEEN's, not mine. The survey said "do not implement
  this yourself" and four iterations demonstrated why.
* The corpus is shaped like a real Twin: a field participates in a realization
  claim AND a lineage edge AND a test-coverage edge, so holding out one
  realization slot leaves the concept identifiable.

Two encodings of the SAME facts, one model, one budget:

* ``binary_hub``  -- today's schema: realization flattened to hub-routed pairs,
  and the roles the schema cannot name (doc_mention, code_use) simply dropped.
* ``reified``     -- the n-ary claim as a claim node with one typed edge per
  slot, carrying every role.

Evaluated on the facts BOTH can express (head to head) and, separately, on the
facts only the n-ary encoding can express -- where the binary model scores zero
by construction. That zero is not a weakness of the baseline; it is the measured
price of the current schema (Arm D).

Run:  <venv>/Scripts/python.exe experiments/tensor_embedding/arm_f_pykeen.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import zlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "runs" / "tensor_embedding_v3"

ROLES = ("type_field", "data_column", "schema_property", "doc_mention", "code_use")
HUB_ROLE = "type_field"
BINARY_REACHABLE = {"type_field", "data_column", "schema_property"}
N_CONCEPTS = 500
CONTAINER_SIZE = 8   # fields per class / columns per table -- shared, so it never leaks the concept
EMB_DIM = 64
EPOCHS = 120
SYLLABLES = ["ka", "ro", "mi", "tan", "vel", "sur", "pex", "dol", "nim", "bra", "quo", "zel"]
TRIGRAM_BUCKETS = 4096


def unique_names(rng, n):
    seen = {}
    while len(seen) < n:
        seen["".join(SYLLABLES[i] for i in rng.integers(0, len(SYLLABLES), size=3))] = None
    return list(seen)


def build_corpus(seed: int, name_mode: str) -> dict:
    """Concepts with realization, lineage and test-coverage -- a real Twin's shape."""
    rng = np.random.default_rng(seed)
    bases = unique_names(rng, N_CONCEPTS)
    concepts = []
    names: dict[str, str] = {}

    for c, base in enumerate(bases):
        roles = [HUB_ROLE] + list(
            rng.choice([r for r in ROLES if r != HUB_ROLE],
                       size=int(rng.integers(3, 5)), replace=False)
        )
        slots = {}
        for role in roles:
            node = f"n{c}:{role}"
            if name_mode == "scramble":
                nm = "".join(SYLLABLES[i] for i in rng.integers(0, len(SYLLABLES), size=3))
            elif name_mode == "mild" and role != HUB_ROLE and rng.random() < 0.6:
                nm = f"bias_{base}" if rng.random() < 0.5 else f"{base}_v2"
            else:
                nm = base
            names[node] = nm
            slots[role] = node
        derived = f"n{c}:derived"
        test = f"n{c}:test"
        names[derived] = f"{names.get(slots.get('data_column', slots[HUB_ROLE]))}_out"
        names[test] = f"test_{base}"
        # Containment. Every field-level node sits in a container -- a class, a
        # table, a schema file, a wiki page -- and containers are SHARED by many
        # concepts, so they narrow without identifying. Without these, a node
        # whose only edge is the held-out one never appears in training at all,
        # and no embedding model can retrieve it (the cold start of M10, which
        # a dry run caught here as 38 of 50 test triples naming an unknown
        # entity).
        container = c // CONTAINER_SIZE
        concepts.append({"id": c, "slots": slots, "derived": derived,
                         "test": test, "container": container})
    return {"concepts": concepts, "names": names}


def encode(corpus: dict, holdout: dict, encoding: str):
    """Return (train_triples, test_triples) for one encoding of the same facts."""
    train, test = [], []
    for con in corpus["concepts"]:
        c = con["id"]
        held_role = holdout[c]
        hub = con["slots"][HUB_ROLE]

        # Facts every encoding shares: lineage, test coverage, containment.
        if "data_column" in con["slots"]:
            train.append((con["slots"]["data_column"], "derives_to", con["derived"]))
        train.append((con["test"], "covers", hub))
        for role, node in con["slots"].items():
            # ONE container entity per group, with a role-typed relation. The
            # first draft used role-specific container entities
            # (`container3:doc_mention` != `container3:data_column`), which left
            # the containers mutually unconnected: there was no path at all from
            # a concept to the container of its held-out slot, and both PyKEEN
            # encodings sat exactly at chance. A class is one entity, not five.
            train.append((node, f"in_{role}_of", f"container{con['container']}"))

        for role, node in con["slots"].items():
            if role == HUB_ROLE:
                continue
            expressible = role in BINARY_REACHABLE
            if encoding == "binary_hub":
                if not expressible:
                    continue                      # today's schema cannot say it
                triple = (hub, f"matches_{role}", node)
            else:
                triple = (f"claim{c}", f"has_{role}", node)
            (test if role == held_role else train).append(triple)
        if encoding == "reified":
            triple = (f"claim{c}", f"has_{HUB_ROLE}", hub)
            (test if held_role == HUB_ROLE else train).append(triple)
    return np.array(train, dtype=str), np.array(test, dtype=str)


def trigram_vec(name: str) -> np.ndarray:
    v = np.zeros(TRIGRAM_BUCKETS)
    padded = f"^{name.lower()}$"
    for i in range(max(0, len(padded) - 2)):
        v[zlib.crc32(padded[i : i + 3].encode("utf-8")) % TRIGRAM_BUCKETS] += 1.0
    return v / (np.linalg.norm(v) + 1e-12)


def trigram_baseline(corpus: dict, holdout: dict, restrict_to_binary: bool) -> dict:
    """The ungrained winner of v1 and v2, on the same held-out facts."""
    nodes = sorted(corpus["names"])
    index = {n: i for i, n in enumerate(nodes)}
    mat = np.stack([trigram_vec(corpus["names"][n]) for n in nodes])
    hits = {1: 0, 10: 0}
    total = 0
    for con in corpus["concepts"]:
        role = holdout[con["id"]]
        if role not in con["slots"]:
            continue
        if restrict_to_binary and role not in BINARY_REACHABLE:
            continue
        target = con["slots"][role]
        query = con["slots"][HUB_ROLE]
        if target == query:
            continue
        scores = mat @ mat[index[query]]
        scores[index[query]] = -np.inf
        order = np.argsort(-scores)
        rank = int(np.where(order == index[target])[0][0])
        total += 1
        for k in hits:
            hits[k] += rank < k
    return {f"@{k}": (round(v / total, 4) if total else None) for k, v in hits.items()} | {
        "queries": total, "candidates": len(nodes)
    }


def run_pykeen(train, test, seed: int) -> dict:
    from pykeen.pipeline import pipeline
    from pykeen.triples import TriplesFactory

    tf_train = TriplesFactory.from_labeled_triples(train)
    tf_test = TriplesFactory.from_labeled_triples(
        test, entity_to_id=tf_train.entity_to_id, relation_to_id=tf_train.relation_to_id
    )
    result = pipeline(
        training=tf_train,
        testing=tf_test,
        model="ComplEx",
        model_kwargs=dict(embedding_dim=EMB_DIM),
        training_kwargs=dict(num_epochs=EPOCHS, use_tqdm=False, use_tqdm_batch=False),
        evaluation_kwargs=dict(use_tqdm=False),
        random_seed=seed,
        device="cpu",
    )
    metrics = result.metric_results.to_dict()["both"]["realistic"]
    return {
        "hits@1": round(float(metrics["hits_at_1"]), 4),
        "hits@10": round(float(metrics["hits_at_10"]), 4),
        "mrr": round(float(metrics["inverse_harmonic_mean_rank"]), 4),
        "train_triples": int(len(train)),
        "test_triples": int(len(test)),
        "entities": int(tf_train.num_entities),
    }


def main() -> int:
    started = time.time()
    payload = {
        "experiment": "tensor-embedding-v3", "arm": "F",
        "implementation": "pykeen", "model": "ComplEx",
        "embedding_dim": EMB_DIM, "epochs": EPOCHS, "concepts": N_CONCEPTS,
        "results": {},
    }
    try:
        import importlib.metadata as md
        import pykeen, torch  # noqa: F401
        payload["pykeen"] = md.version("pykeen")
        payload["torch"] = torch.__version__
    except ImportError as exc:
        print(f"pykeen/torch unavailable: {exc}")
        return 2

    for name_mode in ("scramble", "mild"):
        corpus = build_corpus(seed=4, name_mode=name_mode)
        rng = np.random.default_rng(8)
        holdout = {}
        for con in corpus["concepts"]:
            options = [r for r in con["slots"] if r != HUB_ROLE]
            holdout[con["id"]] = options[int(rng.integers(0, len(options)))]

        block = {}
        for encoding in ("binary_hub", "reified"):
            train, test = encode(corpus, holdout, encoding)
            block[encoding] = run_pykeen(train, test, seed=17)
            print(f"{name_mode:9s} {encoding:11s} hits@1={block[encoding]['hits@1']:.3f} "
                  f"hits@10={block[encoding]['hits@10']:.3f} mrr={block[encoding]['mrr']:.3f} "
                  f"(test n={block[encoding]['test_triples']})")
        block["trigram_on_binary_expressible"] = trigram_baseline(corpus, holdout, True)
        block["trigram_on_all_roles"] = trigram_baseline(corpus, holdout, False)
        print(f"{name_mode:9s} trigram     @1={block['trigram_on_all_roles']['@1']} "
              f"@10={block['trigram_on_all_roles']['@10']}")
        payload["results"][name_mode] = block
        print()

    payload["elapsed_seconds"] = round(time.time() - started, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arm_f.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {OUT / 'arm_f.json'}  ({payload['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
