"""Arm B of EXPERIMENT ``tensor-embedding-v1``: cross-plane binding.

Two substrates, because one of them cannot carry a statistic:

* the real Gate-1 voltage fixture (nine nodes, four queries) -- a demonstration
  with ground truth taken from its own ``fourfold.json``;
* a synthetic sweep (N field triples, controlled name perturbation) -- the only
  part of this arm with a dynamic range, and therefore the only part whose
  numbers mean anything on their own.

Two scenarios on the fixture (SPEC §6a.1):

* ``aligned``  -- the fixture as it sits on disk; every plane spells the field
  the same way, so exact string match is a perfect oracle and the question is
  undiscriminating;
* ``renamed``  -- the half-completed Gate-1 rename: Python says
  ``bias_voltage``, CSV and schema still say ``voltage``. This is the actual
  Renovation defect Gate 1 exists to repair, and exact match fails on it by
  construction.

Run:  python experiments/tensor_embedding/arm_b_fixture.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hrr import atom, bind, bundle, cosine, normalise, text_vector, trigram_book, unbind  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "ignition" / "voltage"
OUT = ROOT / "runs" / "tensor_embedding_v1"

D = 1024
REVISION = "rev-2de997ef"
PLANES = ("code", "type", "data", "knowledge")
KINDS = ("field", "column", "property", "function", "mention")


def fixture_digest() -> str:
    """Pin the substrate. A number from Arm B is about THIS tree and no other."""
    parts = []
    for path in sorted(FIXTURE.rglob("*")):
        if path.is_file():
            rel = path.relative_to(FIXTURE).as_posix()
            parts.append(f"{rel}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def fixture_nodes(python_field_name: str) -> list[dict]:
    """Field-level nodes of the fixture, extracted by hand.

    Seven files. A parser would add a failure mode without adding a fact, and
    the extraction is checked against the fixture text in the same commit.
    """
    return [
        {"id": "type:Event.id", "plane": "type", "kind": "field", "name": "id", "path": "src/ignition_app/models.py"},
        {"id": "type:Event.voltage", "plane": "type", "kind": "field", "name": python_field_name, "path": "src/ignition_app/models.py"},
        {"id": "data:csv.id", "plane": "data", "kind": "column", "name": "id", "path": "data/events.csv"},
        {"id": "data:csv.voltage", "plane": "data", "kind": "column", "name": "voltage", "path": "data/events.csv"},
        {"id": "data:schema.id", "plane": "data", "kind": "property", "name": "id", "path": "schemas/event.schema.json"},
        {"id": "data:schema.voltage", "plane": "data", "kind": "property", "name": "voltage", "path": "schemas/event.schema.json"},
        {"id": "code:parse_event", "plane": "code", "kind": "function", "name": "parse_event", "path": "src/ignition_app/repository.py"},
        {"id": "knowledge:wiki.voltage", "plane": "knowledge", "kind": "mention", "name": "voltage", "path": "wiki/Event.md"},
        {"id": "knowledge:wiki.Event", "plane": "knowledge", "kind": "mention", "name": "Event", "path": "wiki/Event.md"},
    ]


# Ground truth, read off the fixture's own fourfold.json claims.
FIXTURE_QUERIES = [
    ("type:Event.id", ["data:csv.id", "data:csv.voltage"], "data:csv.id"),
    ("type:Event.voltage", ["data:csv.id", "data:csv.voltage"], "data:csv.voltage"),
    ("type:Event.id", ["data:schema.id", "data:schema.voltage"], "data:schema.id"),
    ("type:Event.voltage", ["data:schema.id", "data:schema.voltage"], "data:schema.voltage"),
]


class Representations:
    """The four representations under comparison, built once per seed."""

    def __init__(self, seed: int = 0, d: int = D):
        rng = np.random.default_rng(seed)
        self.d = d
        self.book = trigram_book(d, rng)
        third = d // 3
        self.third = third
        self.book_small = trigram_book(third, np.random.default_rng(seed + 1))
        self.role_name = normalise(rng.normal(0, 1 / np.sqrt(d), d))
        self.role_plane = normalise(rng.normal(0, 1 / np.sqrt(d), d))
        self.role_kind = normalise(rng.normal(0, 1 / np.sqrt(d), d))
        self.role_rev = normalise(rng.normal(0, 1 / np.sqrt(d), d))
        self.plane_atoms = np.stack([atom(p, self.book) for p in PLANES])

    def pooled(self, node: dict) -> np.ndarray:
        """Naive: mean-pool everything into one vector. Loses the roles."""
        return normalise(text_vector(node["name"], self.book) + text_vector(node["path"], self.book))

    def concat(self, node: dict) -> np.ndarray:
        """Slots. The honest rival: separate fields, no algebra."""
        return np.concatenate(
            [
                text_vector(node["name"], self.book_small),
                atom(node["plane"], self.book_small),
                atom(node["kind"], self.book_small),
            ]
        )

    def bound(self, node: dict) -> np.ndarray:
        """HRR: role-filler binding, superposed at fixed width."""
        return bundle(
            [
                bind(self.role_name, text_vector(node["name"], self.book)),
                bind(self.role_plane, atom(node["plane"], self.book)),
                bind(self.role_kind, atom(node["kind"], self.book)),
                bind(self.role_rev, atom(REVISION, self.book)),
            ]
        )

    def score(self, kind: str, query: dict, candidate: dict) -> float:
        if kind == "exact":
            return 1.0 if query["name"] == candidate["name"] else 0.0
        fn = {"pooled": self.pooled, "concat": self.concat, "bound": self.bound}[kind]
        a, b = fn(query), fn(candidate)
        return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12))

    def recovered_plane(self, node: dict) -> str:
        """B1: can the plane be read back out of the vector alone?"""
        noisy = unbind(self.bound(node), self.role_plane)
        return PLANES[int(np.argmax(cosine(noisy, self.plane_atoms)))]

    def recovered_revision(self, node: dict, decoys: list[str]) -> str:
        """B4: can the revision be read back out?"""
        book = np.stack([atom(r, self.book) for r in [REVISION] + decoys])
        noisy = unbind(self.bound(node), self.role_rev)
        return ([REVISION] + decoys)[int(np.argmax(cosine(noisy, book)))]


def run_fixture(reps: Representations, scenario: str, python_name: str) -> dict:
    nodes = {n["id"]: n for n in fixture_nodes(python_name)}
    out = {}
    for kind in ("exact", "pooled", "concat", "bound"):
        hits, detail = 0, []
        for query_id, candidate_ids, truth_id in FIXTURE_QUERIES:
            scores = {c: reps.score(kind, nodes[query_id], nodes[c]) for c in candidate_ids}
            best = max(scores, key=lambda c: (scores[c], c))
            tied = len({round(v, 9) for v in scores.values()}) == 1
            ok = (best == truth_id) and not tied
            hits += int(ok)
            detail.append(
                {
                    "query": query_id,
                    "truth": truth_id,
                    "picked": None if tied else best,
                    "tie": tied,
                    "scores": {c: round(v, 4) for c, v in scores.items()},
                }
            )
        out[kind] = {"top1": hits / len(FIXTURE_QUERIES), "detail": detail}

    planes_ok = sum(reps.recovered_plane(n) == n["plane"] for n in nodes.values())
    decoys = [f"rev-decoy-{i}" for i in range(99)]
    revs_ok = sum(reps.recovered_revision(n, decoys) == REVISION for n in nodes.values())
    out["_plane_recovery_from_bound"] = round(planes_ok / len(nodes), 4)
    out["_revision_recovery_from_bound"] = round(revs_ok / len(nodes), 4)
    out["_scenario"] = scenario
    return out


SYLLABLES = ["ka", "ro", "mi", "tan", "vel", "sur", "pex", "dol", "nim", "bra", "quo", "zel"]


def synth_name(rng: np.random.Generator) -> str:
    """Three syllables, not two.

    The first draft used two, giving 144 possible names for 200 fields. The
    duplicates made every representation look bad in the same way and the
    `exact` control caught it: it scored 0.21 in the `none` mode where it must
    score 1.00 by construction. A control that cannot fail is decoration; this
    one earned its place.
    """
    return "".join(SYLLABLES[i] for i in rng.integers(0, len(SYLLABLES), size=3))


def unique_names(rng: np.random.Generator, n: int) -> list[str]:
    """``n`` distinct names. Collisions are a property of the generator, not
    of any representation, and must not be measured as if they were."""
    seen: dict[str, None] = {}
    while len(seen) < n:
        seen[synth_name(rng)] = None
    return list(seen)


def perturb(name: str, mode: str, rng: np.random.Generator) -> str:
    if mode == "none":
        return name
    if mode == "prefix":
        return f"bias_{name}"
    if mode == "suffix":
        return f"{name}_v2"
    if mode == "abbrev":
        stripped = "".join(c for c in name if c not in "aeiou")
        return stripped or name[:2]
    if mode == "foreign":
        return synth_name(rng)
    raise ValueError(mode)


def run_synthetic(reps: Representations, n: int = 200, seed: int = 7) -> dict:
    """The arm's only real statistic: retrieval under controlled name drift."""
    rng = np.random.default_rng(seed)
    bases = unique_names(rng, n)
    results = {}
    for mode in ("none", "prefix", "suffix", "abbrev", "foreign"):
        # Paths carry the plane and nothing else. The first draft numbered them
        # (`src/m17.py` vs `data/t17.csv`), which let the pooled representation
        # match on the shared trigram `17` -- reading the ground-truth index out
        # of the file path instead of comparing the names. It scored 0.975 that
        # way. Identity must not appear anywhere except in the name.
        candidates = [
            {"id": f"data:{i}", "plane": "data", "kind": "column", "name": bases[i], "path": "data/table.csv"}
            for i in range(n)
        ]
        queries = [
            (
                i,
                {
                    "id": f"type:{i}",
                    "plane": "type",
                    "kind": "field",
                    "name": perturb(bases[i], mode, rng),
                    "path": "src/model.py",
                },
            )
            for i in range(n)
        ]
        per_rep = {}
        for kind in ("exact", "pooled", "concat", "bound"):
            vecs = None
            if kind != "exact":
                fn = {"pooled": reps.pooled, "concat": reps.concat, "bound": reps.bound}[kind]
                vecs = np.stack([normalise(fn(c)) for c in candidates])
            hits = 0
            for truth_idx, query in queries:
                if kind == "exact":
                    matches = [i for i, c in enumerate(candidates) if c["name"] == query["name"]]
                    hits += int(len(matches) == 1 and matches[0] == truth_idx)
                else:
                    qv = normalise(fn(query))
                    hits += int(int(np.argmax(vecs @ qv)) == truth_idx)
            per_rep[kind] = round(hits / n, 4)
        results[mode] = per_rep
    return results


def main() -> int:
    started = time.time()
    reps = Representations(seed=0)
    payload = {
        "experiment": "tensor-embedding-v1",
        "arm": "B",
        "dimension": D,
        "numpy": np.__version__,
        "fixture": str(FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "fixture_tree_digest": fixture_digest(),
        "fixture_node_count": len(fixture_nodes("voltage")),
        "fixture_query_count": len(FIXTURE_QUERIES),
        "chance_top1_on_fixture": 0.5,
        "aligned": run_fixture(reps, "aligned", "voltage"),
        "renamed": run_fixture(reps, "renamed", "bias_voltage"),
        "synthetic": run_synthetic(reps),
        "synthetic_n": 200,
        "synthetic_chance_top1": 1 / 200,
    }
    payload["elapsed_seconds"] = round(time.time() - started, 2)

    for scenario in ("aligned", "renamed"):
        print(f"-- fixture / {scenario} (4 queries, chance 0.50)")
        for kind in ("exact", "pooled", "concat", "bound"):
            print(f"     {kind:8s} top1={payload[scenario][kind]['top1']:.2f}")
        print(f"     plane recovered from bound: {payload[scenario]['_plane_recovery_from_bound']}")
        print(f"     revision recovered from bound: {payload[scenario]['_revision_recovery_from_bound']}")
    print("\n-- synthetic sweep (n=200, chance 0.005)")
    print(f"     {'mode':9s} {'exact':>7s} {'pooled':>7s} {'concat':>7s} {'bound':>7s}")
    for mode, row in payload["synthetic"].items():
        print(f"     {mode:9s} {row['exact']:7.3f} {row['pooled']:7.3f} {row['concat']:7.3f} {row['bound']:7.3f}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arm_b.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nwrote {OUT / 'arm_b.json'}  ({payload['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
