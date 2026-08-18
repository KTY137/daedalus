"""EXPERIMENT s05 probe: does a four-plane snapshot replay to the same digest?

Read-only, pure stdlib, no repository imports, no writes, no network, no
subprocess; one JSON object on stdout -- the same frame the other forest_v2
probes use.

It measures four things against the real tree, and reports raw numbers:

1. **Replay identity.**  Extract and build twice in one process.  Equal
   snapshot digest or the claim is dead.
2. **Independence.**  The digest must not move when the root is spelled
   differently, when node/edge order is shuffled, or when the documents make a
   JSON round trip.  Each of those is a way an absolute path, an iteration
   order, or a serializer could have leaked into the digest.
3. **Field sensitivity.**  Mutate exactly one contract field at a time and see
   whether the snapshot digest moves.  This is the check that every digested
   field is load-bearing -- a field the builder ignores is a field an attacker
   or a bug can change for free.  ``producer`` is expected NOT to move it: it
   is manifest provenance, so s01-s04 can replace these placeholder extractors
   without invalidating an identical extraction.
4. **Refusal matrix.**  Every way a partial or inconsistent plane set can be
   offered, and the refusal code it produces.  Master plan invariant 6: a
   partial graph state must not masquerade as a revision.

Cross-process identity (different ``PYTHONHASHSEED``) is deliberately NOT
measured in here -- a probe that shells out is no longer read-only.  Run the
probe twice from the shell and compare ``snapshot_digest``.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reference_planes as rp  # noqa: E402
from snapshot import (  # noqa: E402
    ContractError,
    build_snapshot,
    canonical_bytes,
    PLANES,
)

SHUFFLE_SEED = 20260818


def _clone(documents):
    return json.loads(json.dumps(documents))


def _digest_of(documents) -> str:
    return build_snapshot(documents)["snapshot_digest"]


def _refusal(documents) -> str:
    try:
        build_snapshot(documents)
    except ContractError as exc:
        return exc.code
    return "NOT_REFUSED"


# --------------------------------------------------------------------------
# single-field mutators (each returns a mutated deep copy)
# --------------------------------------------------------------------------


def _first_plane(documents, plane):
    return next(d for d in documents if d["plane"] == plane)


def _mutate_node_id(docs):
    doc = _first_plane(docs, "code")
    old = doc["nodes"][0]["id"]
    new = old + "~s05"
    doc["nodes"][0]["id"] = new
    for edge in doc["edges"]:
        for end in ("src", "dst"):
            if edge[end] == old:
                edge[end] = new
    return docs


def _mutate_node_kind(docs):
    _first_plane(docs, "code")["nodes"][0]["kind"] += "~s05"
    return docs


def _mutate_locator_path(docs):
    _first_plane(docs, "code")["nodes"][0]["locator"]["path"] += ".s05"
    return docs


def _mutate_locator_line(docs):
    node = _first_plane(docs, "knowledge")["nodes"][-1]
    node["locator"]["start_line"] += 1
    node["locator"]["end_line"] = max(node["locator"]["end_line"], node["locator"]["start_line"])
    return docs


def _mutate_attrs(docs):
    _first_plane(docs, "data")["nodes"][0]["attrs"]["fields"] = -1
    return docs


def _mutate_edge_kind(docs):
    _first_plane(docs, "type")["edges"][0]["kind"] += "~s05"
    return docs


def _drop_edge(docs):
    _first_plane(docs, "type")["edges"].pop()
    return docs


def _drop_node(docs):
    doc = _first_plane(docs, "knowledge")
    dropped = doc["nodes"].pop()["id"]
    doc["edges"] = [e for e in doc["edges"] if dropped not in (e["src"], e["dst"])]
    return docs


def _mutate_revision(docs):
    for doc in docs:
        doc["revision"] = doc["revision"] + "0"
    return docs


def _mutate_producer(docs):
    for doc in docs:
        doc["producer"] = "s01_code.extract"
    return docs


FIELD_MUTATIONS = (
    ("node.id", _mutate_node_id, True),
    ("node.kind", _mutate_node_kind, True),
    ("node.locator.path", _mutate_locator_path, True),
    ("node.locator.start_line", _mutate_locator_line, True),
    ("node.attrs.value", _mutate_attrs, True),
    ("edge.kind", _mutate_edge_kind, True),
    ("edge.dropped", _drop_edge, True),
    ("node.dropped", _drop_node, True),
    ("revision", _mutate_revision, True),
    ("producer", _mutate_producer, False),
)


# --------------------------------------------------------------------------
# refusal cases
# --------------------------------------------------------------------------


def _case_missing_plane(docs):
    return [d for d in docs if d["plane"] != "data"]


def _case_duplicate_plane(docs):
    return docs + [_clone([_first_plane(docs, "code")])[0]]


def _case_revision_mismatch(docs):
    _first_plane(docs, "type")["revision"] += "1"
    return docs


def _case_duplicate_node_id(docs):
    doc = _first_plane(docs, "code")
    doc["nodes"].append(_clone([doc["nodes"][0]])[0])
    return docs


def _case_dangling_edge(docs):
    doc = _first_plane(docs, "code")
    doc["edges"].append(
        {"src": doc["nodes"][0]["id"], "dst": "code:module:no-such-file.py", "kind": "defined_in", "attrs": {}}
    )
    return docs


def _case_cross_plane_edge(docs):
    code = _first_plane(docs, "code")
    knowledge = _first_plane(docs, "knowledge")
    code["edges"].append(
        {"src": code["nodes"][0]["id"], "dst": knowledge["nodes"][0]["id"], "kind": "documented_by", "attrs": {}}
    )
    return docs


def _case_unknown_key(docs):
    _first_plane(docs, "data")["nodes"][0]["built_at"] = "2026-08-18T00:00:00Z"
    return docs


def _case_absolute_locator(docs):
    _first_plane(docs, "code")["nodes"][0]["locator"]["path"] = "/abs/path/mod.py"
    return docs


def _case_unknown_plane(docs):
    _first_plane(docs, "data")["plane"] = "runtime"
    return docs


def _case_bad_schema(docs):
    _first_plane(docs, "code")["schema"] = "forest-v2-plane-extraction/2"
    return docs


REFUSAL_CASES = (
    ("missing_plane", _case_missing_plane),
    ("duplicate_plane", _case_duplicate_plane),
    ("revision_mismatch", _case_revision_mismatch),
    ("duplicate_node_id", _case_duplicate_node_id),
    ("dangling_edge", _case_dangling_edge),
    ("cross_plane_edge", _case_cross_plane_edge),
    ("unknown_key", _case_unknown_key),
    ("absolute_locator", _case_absolute_locator),
    ("unknown_plane", _case_unknown_plane),
    ("bad_schema", _case_bad_schema),
)


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------


def probe(root: Path) -> dict:
    revision = rp.read_git_revision(root)
    revision_source = "git-head" if revision else "fallback"
    if not revision:
        revision = "unknown-revision"

    t0 = time.perf_counter()
    build_a = build_snapshot(rp.extract_all(root, revision))
    t1 = time.perf_counter()
    docs_b = rp.extract_all(root, revision)
    build_b = build_snapshot(docs_b)
    t2 = time.perf_counter()

    # independence: a different spelling of the same root
    spelled = root / rp.CODE_ROOTS[0] / ".."
    alt_root = spelled if spelled.is_dir() else root
    alt_spelling = _digest_of(rp.extract_all(alt_root, revision))

    # independence: shuffled element order
    shuffled = _clone(docs_b)
    rng = random.Random(SHUFFLE_SEED)
    for doc in shuffled:
        rng.shuffle(doc["nodes"])
        rng.shuffle(doc["edges"])
    shuffled_digest = _digest_of(shuffled)

    # independence: JSON round trip through the canonical form
    round_trip = [json.loads(canonical_bytes(doc).decode("utf-8")) for doc in docs_b]
    round_trip_digest = _digest_of(round_trip)

    sensitivity = []
    for label, mutate, expect_change in FIELD_MUTATIONS:
        try:
            mutated = _digest_of(mutate(_clone(docs_b)))
            changed = mutated != build_b["snapshot_digest"]
            outcome = "changed" if changed else "unchanged"
        except ContractError as exc:  # a mutation the contract itself refuses
            changed = None
            outcome = f"refused:{exc.code}"
        sensitivity.append(
            {
                "field": label,
                "expected": "changed" if expect_change else "unchanged",
                "observed": outcome,
                "as_expected": (changed is not None) and (changed == expect_change),
            }
        )

    refusals = []
    for label, case in REFUSAL_CASES:
        code = _refusal(case(_clone(docs_b)))
        refusals.append({"case": label, "code": code, "refused": code != "NOT_REFUSED"})

    canonical_sizes = {
        doc["plane"]: len(canonical_bytes(doc)) for doc in docs_b
    }

    digest_text = json.dumps(build_a, sort_keys=True)
    return {
        "schema": "forest-v2-s05-replay-identity-probe/1",
        "read_only": True,
        "revision": revision,
        "revision_source": revision_source,
        "replay": {
            "digest_build_1": build_a["snapshot_digest"],
            "digest_build_2": build_b["snapshot_digest"],
            "identical": build_a["snapshot_digest"] == build_b["snapshot_digest"],
            "manifest_identical": digest_text == json.dumps(build_b, sort_keys=True),
            "build_1_seconds": round(t1 - t0, 3),
            "build_2_seconds": round(t2 - t1, 3),
        },
        "independence": {
            "alt_root_spelling": {
                "root": str(alt_root) != str(root),
                "digest": alt_spelling,
                "identical": alt_spelling == build_b["snapshot_digest"],
            },
            "shuffled_order": {
                "digest": shuffled_digest,
                "identical": shuffled_digest == build_b["snapshot_digest"],
            },
            "json_round_trip": {
                "digest": round_trip_digest,
                "identical": round_trip_digest == build_b["snapshot_digest"],
            },
        },
        "planes": build_a["planes"],
        "node_total": build_a["node_total"],
        "edge_total": build_a["edge_total"],
        "canonical_bytes_per_plane": canonical_sizes,
        "canonical_bytes_total": sum(canonical_sizes.values()),
        "field_sensitivity": sensitivity,
        "field_sensitivity_as_expected": sum(1 for s in sensitivity if s["as_expected"]),
        "field_sensitivity_cases": len(sensitivity),
        "refusal_matrix": refusals,
        "refusals_correct": sum(1 for r in refusals if r["code"] == r["case"]),
        "refusal_cases": len(refusals),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(__file__).resolve().parents[3]
    print(json.dumps(probe(root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
