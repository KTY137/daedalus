"""EXPERIMENT ``tensor-embedding-v2``: does arity pay?

v1 settled the fixed-role question: slot concatenation beat HRR binding at all
45 measured points. But concatenation compares PAIRWISE. A statement about three
things at once it can only form as a sum of three two-way statements.

This arm asks whether that limit costs anything, and -- more importantly --
whether real cross-plane bindings ever need three-way agreement at all.

No model is trained. The n-ary generalisation of cosine is the trilinear form
``sum_r a_r b_r c_r``: a product collapses as soon as ONE factor disagrees,
where a sum of pairwise similarities stays high when two of three agree.

Run:  python experiments/tensor_embedding/arm_c_arity.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hrr import TRIGRAM_BOOK_SIZE, normalise, trigram_book  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "runs" / "tensor_embedding_v2"
FIXTURE_CLAIMS = ROOT / "tests" / "fixtures" / "ignition" / "voltage" / "fourfold.json"

D = 1024
N_CONCEPTS = 200
CANDIDATES = 40
DATATYPES = ("string", "number", "boolean", "timestamp")
DISTRACTOR_SHARES = (0.0, 0.2, 0.4, 0.6, 0.8)
SYLLABLES = ["ka", "ro", "mi", "tan", "vel", "sur", "pex", "dol", "nim", "bra", "quo", "zel"]


def unique_names(rng: np.random.Generator, n: int) -> list[str]:
    seen: dict[str, None] = {}
    while len(seen) < n:
        seen["".join(SYLLABLES[i] for i in rng.integers(0, len(SYLLABLES), size=3))] = None
    return list(seen)


class Corpus:
    """N concepts, each realised as a type field, a CSV column, a schema property."""

    def __init__(self, seed: int, book: np.ndarray, rename: str = "none"):
        rng = np.random.default_rng(seed)
        self.book = book
        self.names = unique_names(rng, N_CONCEPTS)
        self.types = [DATATYPES[i] for i in rng.integers(0, len(DATATYPES), size=N_CONCEPTS)]
        self.rename = rename
        self.q = np.stack([self._vec(self._query_name(i), self.types[i]) for i in range(N_CONCEPTS)])
        self.csv = np.stack([self._vec(self.names[i], self.types[i]) for i in range(N_CONCEPTS)])
        self.schema = np.stack([self._vec(self.names[i], self.types[i]) for i in range(N_CONCEPTS)])

    def _query_name(self, i: int) -> str:
        base = self.names[i]
        if self.rename == "prefix":
            return f"bias_{base}"
        if self.rename == "suffix":
            return f"{base}_v2"
        return base

    def _vec(self, name: str, datatype: str) -> np.ndarray:
        """A NON-NEGATIVE trigram histogram, not a random projection.

        The first draft used the zero-mean projected vectors from v1. On those,
        the trilinear form is not a similarity at all: for the true triple
        q ~ c1 ~ c2 it reduces to a sum of cubes of a symmetric zero-mean
        distribution, which is ~0. It scored 0.09 against a chance level of
        0.025 -- indistinguishable from noise, for every regime.

        That is itself the finding: ``sum_r a_r b_r c_r`` only becomes a
        similarity when the components are non-negative, or when the embeddings
        are TRAINED to make it one -- which is exactly what RESCAL, DistMult
        and ComplEx do, and exactly the cost this experiment was trying to
        avoid. Non-negative histograms are the honest way to ask the arity
        question without training.
        """
        vec = np.zeros(TRIGRAM_BOOK_SIZE + len(DATATYPES))
        padded = f"^{name.lower()}$"
        for i in range(max(0, len(padded) - 2)):
            vec[zlib.crc32(padded[i : i + 3].encode("utf-8")) % TRIGRAM_BOOK_SIZE] += 1.0
        vec[TRIGRAM_BOOK_SIZE + DATATYPES.index(datatype)] = 0.5
        return normalise(vec)


def score(kind: str, q: np.ndarray, c1: np.ndarray, c2: np.ndarray) -> np.ndarray:
    """Score a query against arrays of (candidate-1, candidate-2) pairs."""
    s_q1 = c1 @ q
    s_q2 = c2 @ q
    s_12 = np.sum(c1 * c2, axis=1)
    if kind == "pairwise_sum":
        return s_q1 + s_q2 + s_12
    if kind == "pairwise_min":
        return np.minimum(np.minimum(s_q1, s_q2), s_12)
    if kind == "trilinear":
        return np.sum(q[None, :] * c1 * c2, axis=1)
    raise ValueError(kind)


def build_candidates(corpus: Corpus, i: int, share: float, rng: np.random.Generator):
    """Candidate pairs for query ``i``: the truth, plus distractors.

    A distractor of the `joint` kind pairs the RIGHT csv column with a WRONG
    schema property. Pairwise evidence then looks strong on one side -- which is
    exactly what a half-completed rename leaves behind in a real repository.
    """
    n_dis = int(round((CANDIDATES - 1) * share))
    others = [j for j in range(N_CONCEPTS) if j != i]
    joint = rng.choice(others, size=n_dis, replace=False) if n_dis else np.array([], dtype=int)
    rest = rng.choice(others, size=(CANDIDATES - 1 - n_dis), replace=False)

    idx1 = [i] + [i] * len(joint) + list(rest)          # csv side
    idx2 = [i] + list(joint) + list(rest)               # schema side
    return np.array(idx1), np.array(idx2)


def run_regime(corpus: Corpus, regime: str, seed: int = 11) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    for share in DISTRACTOR_SHARES:
        hits = {k: 0 for k in ("exact", "pairwise_sum", "pairwise_min", "trilinear")}
        for i in range(N_CONCEPTS):
            share_used = share if regime == "joint" else 0.0
            idx1, idx2 = build_candidates(corpus, i, share_used, rng)
            if regime == "decomposable" and share > 0:
                # Same candidate count, but distractors are unrelated on BOTH
                # sides -- pairwise evidence is then sufficient by construction.
                n_dis = int(round((CANDIDATES - 1) * share))
                others = [j for j in range(N_CONCEPTS) if j != i]
                pick = rng.choice(others, size=CANDIDATES - 1, replace=False)
                idx1 = np.array([i] + list(pick))
                idx2 = np.array([i] + list(pick))
                del n_dis
            c1, c2 = corpus.csv[idx1], corpus.schema[idx2]
            q = corpus.q[i]
            for kind in ("pairwise_sum", "pairwise_min", "trilinear"):
                best = int(np.argmax(score(kind, q, c1, c2)))
                hits[kind] += int(idx1[best] == i and idx2[best] == i)
            qname = corpus._query_name(i)
            exact_hit = [
                p for p in range(len(idx1))
                if corpus.names[idx1[p]] == qname and corpus.names[idx2[p]] == qname
            ]
            hits["exact"] += int(len(exact_hit) == 1 and idx1[exact_hit[0]] == i)
        out[f"{share:.1f}"] = {k: round(v / N_CONCEPTS, 4) for k, v in hits.items()}
    return out


def real_binding_arity() -> dict:
    """K8: are real cross-plane claims ever irreducibly three-way?

    Measured against the repository's own ground truth, not the synthetic
    corpus. Keys are mapped to PLANES explicitly. The first draft derived the
    plane from the key's prefix, which counted ``link_target`` and
    ``target_node_id`` as two different planes when both name the same target
    side -- and reported 5 of 10 claims as arity>=3 on that basis. Wrong.
    """
    key_to_plane = {
        "code_file": "code",
        "type_file": "type", "type_name": "type", "type_field": "type",
        "csv_file": "data", "csv_field": "data",
        "schema_file": "data", "schema_field": "data",
        "wiki_file": "knowledge",
        "target_plane": None, "link_target": None, "target_node_id": None,
    }
    claims = json.loads(FIXTURE_CLAIMS.read_text(encoding="utf-8"))["claims"]
    per_claim = []
    for claim in claims:
        planes = set()
        for key, value in claim.items():
            if key == "kind":
                continue
            mapped = key_to_plane.get(key, "?")
            if mapped:
                planes.add(mapped)
        if "target_plane" in claim:
            planes.add(claim["target_plane"])
        per_claim.append({"kind": claim["kind"], "planes": sorted(planes), "arity": len(planes)})
    arities = [c["arity"] for c in per_claim]
    return {
        "source": str(FIXTURE_CLAIMS.relative_to(ROOT)).replace("\\", "/"),
        "claim_count": len(claims),
        "arity_histogram": {str(a): arities.count(a) for a in sorted(set(arities))},
        "claims_with_arity_ge_3": sum(a >= 3 for a in arities),
        "per_claim": per_claim,
    }


def main() -> int:
    started = time.time()
    book = trigram_book(D, np.random.default_rng(0))
    payload = {
        "experiment": "tensor-embedding-v2",
        "dimension": D,
        "concepts": N_CONCEPTS,
        "candidates_per_query": CANDIDATES,
        "chance_top1": round(1 / CANDIDATES, 4),
        "numpy": np.__version__,
        "regimes": {},
        "k8_real_binding_arity": real_binding_arity(),
    }
    for rename in ("none", "prefix"):
        corpus = Corpus(seed=3, book=book, rename=rename)
        for regime in ("decomposable", "joint"):
            key = f"{regime}/rename={rename}"
            payload["regimes"][key] = run_regime(corpus, regime)
            print(f"-- {key}  (chance {payload['chance_top1']})")
            print(f"   {'share':>6s} {'exact':>8s} {'pw_sum':>8s} {'pw_min':>8s} {'trilin':>8s}")
            for share, row in payload["regimes"][key].items():
                print(
                    f"   {share:>6s} {row['exact']:8.3f} {row['pairwise_sum']:8.3f} "
                    f"{row['pairwise_min']:8.3f} {row['trilinear']:8.3f}"
                )

    k8 = payload["k8_real_binding_arity"]
    print(f"\n-- K8 real claims: {k8['claim_count']} total, "
          f"arity>=3: {k8['claims_with_arity_ge_3']}, histogram {k8['arity_histogram']}")

    payload["elapsed_seconds"] = round(time.time() - started, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arm_c.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nwrote {OUT / 'arm_c.json'}  ({payload['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
