"""EXPERIMENT s05 probe: does a four-plane snapshot replay to the same digest?

Read-only, pure stdlib, no repository imports, no writes, no network, no
subprocess; one JSON object on stdout -- the same frame the other forest_v2
probes use.

It measures five things against the real tree, and reports raw numbers:

1. **Replay identity.**  Extract and build twice in one process.  Equal
   snapshot digest or the claim is dead.
2. **Independence.**  The digest must not move when the root is spelled
   differently, when node/edge order is shuffled, or when the documents make a
   JSON round trip.  Each of those is a way an absolute path, an iteration
   order, or a serializer could have leaked into the digest.
3. **Field sensitivity.**  Mutate exactly ONE field of ONE object and record
   what happens.  Three outcomes are legitimate and each is stated up front per
   mutator: the digest moves (the field is digested), the digest holds (the
   field is provenance), or the build is refused with a named code (the field
   is guarded).  A mutator that cannot be expressed as one field says so and is
   counted as skipped rather than quietly padding the score.
4. **Structure sensitivity.**  Dropping a node or an edge is not a field
   mutation; those are reported separately so the field number stays clean.
5. **Refusal matrix.**  Every way a partial, inconsistent, or unevidenced plane
   set can be offered, and the refusal code it produces.

Timing is reported per phase -- opening scan, extraction, build, closing scan.
An earlier revision of this probe folded extraction and build into one number,
which made the build look far more expensive than it is.

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

CHANGED = "changed"
UNCHANGED = "unchanged"


def _clone(payload):
    return json.loads(json.dumps(payload))


def _digest_of(documents, scope) -> str:
    return build_snapshot(documents, scope)["snapshot_digest"]


def _refusal(documents, scope) -> str:
    try:
        build_snapshot(documents, scope)
    except ContractError as exc:
        return exc.code
    return "NOT_REFUSED"


class Skip(Exception):
    """The tree offers no object on which this mutation is single-field."""


# --------------------------------------------------------------------------
# single-field mutators
#
# Each takes (documents, scope) and mutates ONE field of ONE object in place.
# Where the contract makes a lone change incoherent (a revision label that must
# match across planes, a file digest that must match across its readers), the
# label says so and the mutator restates the same field in every document that
# holds it -- one field, every copy of it, nothing else.
# --------------------------------------------------------------------------


def _plane(documents, plane):
    return next(d for d in documents if d["plane"] == plane)


def _isolated_node(documents):
    """A node no edge touches: the only place a lone id rename stays coherent."""
    for doc in documents:
        attached = set()
        for edge in doc["edges"]:
            attached.add(edge["src"])
            attached.add(edge["dst"])
        for node in doc["nodes"]:
            if node["id"] not in attached:
                return doc, node
    raise Skip("no node without an incident edge")


def _spanning_node(documents):
    """A node whose locator spans more than one line, so start_line may move up."""
    for doc in documents:
        for node in doc["nodes"]:
            if node["locator"]["end_line"] > node["locator"]["start_line"] + 1:
                return doc, node
    raise Skip("no node with a multi-line locator")


def _mutate_isolated_node_id(docs, scope):
    _, node = _isolated_node(docs)
    node["id"] += "~s05"


def _mutate_connected_node_id(docs, scope):
    doc = _plane(docs, "code")
    attached = {e["src"] for e in doc["edges"]} | {e["dst"] for e in doc["edges"]}
    for node in doc["nodes"]:
        if node["id"] in attached:
            node["id"] += "~s05"
            return
    raise Skip("no node with an incident edge")


def _mutate_node_kind(docs, scope):
    _plane(docs, "code")["nodes"][0]["kind"] += "~s05"


def _mutate_locator_path(docs, scope):
    _plane(docs, "code")["nodes"][0]["locator"]["path"] += ".s05"


def _mutate_locator_start_line(docs, scope):
    _, node = _spanning_node(docs)
    node["locator"]["start_line"] += 1


def _mutate_locator_end_line(docs, scope):
    _plane(docs, "knowledge")["nodes"][0]["locator"]["end_line"] += 1


def _mutate_node_attrs(docs, scope):
    for doc in docs:
        for node in doc["nodes"]:
            for key, value in node["attrs"].items():
                node["attrs"][key] = f"{value}~s05"
                return
    raise Skip("no node carries an attr")


def _mutate_edge_src(docs, scope):
    doc = _plane(docs, "type")
    edge = doc["edges"][0]
    for node in doc["nodes"]:
        if node["id"] != edge["src"]:
            edge["src"] = node["id"]
            return
    raise Skip("plane has a single node id")


def _mutate_edge_dst(docs, scope):
    doc = _plane(docs, "type")
    edge = doc["edges"][0]
    for node in doc["nodes"]:
        if node["id"] != edge["dst"]:
            edge["dst"] = node["id"]
            return
    raise Skip("plane has a single node id")


def _mutate_edge_kind(docs, scope):
    _plane(docs, "type")["edges"][0]["kind"] += "~s05"


def _mutate_edge_attrs(docs, scope):
    _plane(docs, "type")["edges"][0]["attrs"]["s05"] = 1


def _mutate_witness_digest(docs, scope):
    """One file's content digest, restated in every plane that read it."""
    path = sorted(_plane(docs, "code")["witness"])[0]
    forged = rp.text_digest("s05 forged content")
    for doc in docs:
        if path in doc["witness"]:
            doc["witness"][path] = forged


def _mutate_witness_and_scope(docs, scope):
    """The same file digest, restated in the witnesses AND in the bracket.

    This is what a real source edit looks like to the builder: coherent
    everywhere.  It is two fields on purpose -- it is the only way to show the
    witness is digested rather than merely guarded.
    """
    path = sorted(_plane(docs, "code")["witness"])[0]
    forged = rp.text_digest("s05 forged content")
    for doc in docs:
        if path in doc["witness"]:
            doc["witness"][path] = forged
    scope["opened"][path] = forged
    scope["closed"][path] = forged


def _mutate_witness_path(docs, scope):
    """Repoint one witness entry at another file.

    Measured outcome is ``unwitnessed_locator``, not ``witness_outside_scope``:
    moving the key also strips the evidence for the nodes located in the old
    file, and the document-level check runs before the scope-level one.  The
    scope-level code has its own exact case in the refusal matrix.
    """
    doc = _plane(docs, "knowledge")
    path = sorted(doc["witness"])[0]
    doc["witness"]["s05-unbracketed/" + path] = doc["witness"].pop(path)


def _mutate_scope_opened(docs, scope):
    path = sorted(scope["opened"])[0]
    scope["opened"][path] = rp.text_digest("s05 forged bracket")


def _mutate_revision_one_plane(docs, scope):
    _plane(docs, "type")["revision"] += "~s05"


def _mutate_revision_all_planes(docs, scope):
    """One field, every copy: planes that disagree are refused before digesting."""
    for doc in docs:
        doc["revision"] += "~s05"


def _mutate_producer(docs, scope):
    for doc in docs:
        doc["producer"] = "s01_code.extract"


FIELD_MUTATIONS = (
    ("node.id [isolated]", _mutate_isolated_node_id, CHANGED),
    ("node.id [connected]", _mutate_connected_node_id, "refused:dangling_edge"),
    ("node.kind", _mutate_node_kind, CHANGED),
    ("node.locator.path", _mutate_locator_path, "refused:unwitnessed_locator"),
    ("node.locator.start_line", _mutate_locator_start_line, CHANGED),
    ("node.locator.end_line", _mutate_locator_end_line, CHANGED),
    ("node.attrs.<value>", _mutate_node_attrs, CHANGED),
    ("edge.src", _mutate_edge_src, CHANGED),
    ("edge.dst", _mutate_edge_dst, CHANGED),
    ("edge.kind", _mutate_edge_kind, CHANGED),
    ("edge.attrs.<value>", _mutate_edge_attrs, CHANGED),
    ("witness.<path> digest", _mutate_witness_digest, "refused:witness_scope_mismatch"),
    ("witness.<path> digest + bracket", _mutate_witness_and_scope, CHANGED),
    ("witness.<path> key", _mutate_witness_path, "refused:unwitnessed_locator"),
    ("scope.opened.<path>", _mutate_scope_opened, "refused:scope_drift"),
    ("revision [one plane]", _mutate_revision_one_plane, "refused:revision_mismatch"),
    ("revision [all planes]", _mutate_revision_all_planes, CHANGED),
    ("producer [all planes]", _mutate_producer, UNCHANGED),
)


# --------------------------------------------------------------------------
# structure mutators -- not field mutations, reported separately
# --------------------------------------------------------------------------


def _drop_edge(docs, scope):
    _plane(docs, "type")["edges"].pop()


def _drop_node(docs, scope):
    doc, node = _isolated_node(docs)
    doc["nodes"].remove(node)


def _drop_witness_entry(docs, scope):
    doc = _plane(docs, "code")
    doc["witness"].pop(sorted(doc["witness"])[0])


STRUCTURE_MUTATIONS = (
    ("drop one edge", _drop_edge, CHANGED),
    ("drop one isolated node", _drop_node, CHANGED),
    ("drop one witness entry", _drop_witness_entry, "refused:unwitnessed_locator"),
)


# --------------------------------------------------------------------------
# refusal cases
# --------------------------------------------------------------------------


def _case_missing_plane(docs, scope):
    return [d for d in docs if d["plane"] != "data"], scope


def _case_duplicate_plane(docs, scope):
    return docs + [_clone(_plane(docs, "code"))], scope


def _case_revision_mismatch(docs, scope):
    _plane(docs, "type")["revision"] += "1"
    return docs, scope


def _case_duplicate_node_id(docs, scope):
    doc = _plane(docs, "code")
    doc["nodes"].append(_clone(doc["nodes"][0]))
    return docs, scope


def _case_dangling_edge(docs, scope):
    doc = _plane(docs, "code")
    doc["edges"].append(
        {
            "src": doc["nodes"][0]["id"],
            "dst": "code:module:no-such-file.py",
            "kind": "defined_in",
            "attrs": {},
        }
    )
    return docs, scope


def _case_cross_plane_edge(docs, scope):
    code, knowledge = _plane(docs, "code"), _plane(docs, "knowledge")
    code["edges"].append(
        {
            "src": code["nodes"][0]["id"],
            "dst": knowledge["nodes"][0]["id"],
            "kind": "documented_by",
            "attrs": {},
        }
    )
    return docs, scope


def _case_unknown_key(docs, scope):
    _plane(docs, "data")["nodes"][0]["built_at"] = "2026-08-18T00:00:00Z"
    return docs, scope


def _case_absolute_locator(docs, scope):
    _plane(docs, "code")["nodes"][0]["locator"]["path"] = "/abs/path/mod.py"
    return docs, scope


def _case_unknown_plane(docs, scope):
    _plane(docs, "data")["plane"] = "runtime"
    return docs, scope


def _case_bad_schema(docs, scope):
    _plane(docs, "code")["schema"] = "forest-v2-plane-extraction/9"
    return docs, scope


def _case_scope_drift(docs, scope):
    scope["closed"][sorted(scope["closed"])[0]] = rp.text_digest("s05 drifted")
    return docs, scope


def _case_witness_conflict(docs, scope):
    code = _plane(docs, "code")
    shared = sorted(set(code["witness"]) & set(_plane(docs, "type")["witness"]))
    code["witness"][shared[0]] = rp.text_digest("s05 disagreement")
    return docs, scope


def _case_witness_scope_mismatch(docs, scope):
    path = sorted(_plane(docs, "knowledge")["witness"])[0]
    for doc in docs:
        if path in doc["witness"]:
            doc["witness"][path] = rp.text_digest("s05 never bracketed")
    return docs, scope


def _case_witness_outside_scope(docs, scope):
    doc = _plane(docs, "knowledge")
    path = sorted(doc["witness"])[0]
    doc["witness"]["s05-unbracketed/" + path] = doc["witness"][path]
    return docs, scope


def _case_nodes_without_witness(docs, scope):
    _plane(docs, "code")["witness"] = {}
    return docs, scope


def _case_unwitnessed_locator(docs, scope):
    doc = _plane(docs, "data")
    doc["witness"].pop(sorted(doc["witness"])[0])
    return docs, scope


def _case_bad_scope(docs, scope):
    scope["opened"] = {"a/b.py": "not-a-digest"}
    return docs, scope


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
    ("scope_drift", _case_scope_drift),
    ("witness_conflict", _case_witness_conflict),
    ("witness_scope_mismatch", _case_witness_scope_mismatch),
    ("witness_outside_scope", _case_witness_outside_scope),
    ("nodes_without_witness", _case_nodes_without_witness),
    ("unwitnessed_locator", _case_unwitnessed_locator),
    ("bad_scope", _case_bad_scope),
)


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------


def _run_mutations(table, documents, scope, baseline):
    results = []
    for label, mutate, expected in table:
        docs, mutated_scope = _clone(documents), _clone(scope)
        try:
            mutate(docs, mutated_scope)
        except Skip as reason:
            results.append(
                {"field": label, "expected": expected, "observed": f"skipped:{reason}"}
            )
            continue
        try:
            observed = CHANGED if _digest_of(docs, mutated_scope) != baseline else UNCHANGED
        except ContractError as exc:
            observed = f"refused:{exc.code}"
        results.append({"field": label, "expected": expected, "observed": observed})
    for entry in results:
        entry["as_expected"] = entry["observed"] == entry["expected"]
    return results


def _timed_build(root: Path, revision: str) -> tuple[dict, list, dict, dict]:
    """One atomic build with each phase timed separately."""
    t0 = time.perf_counter()
    opened = rp.scan_scope(root)
    t1 = time.perf_counter()
    documents = rp.extract_all(root, revision)
    t2 = time.perf_counter()
    closed = rp.scan_scope(root)
    t3 = time.perf_counter()
    scope = {"roots": list(rp.SCOPE_ROOTS), "opened": opened, "closed": closed}
    manifest = build_snapshot(documents, scope)
    t4 = time.perf_counter()
    timing = {
        "scan_open_seconds": round(t1 - t0, 3),
        "extract_all_seconds": round(t2 - t1, 3),
        "scan_close_seconds": round(t3 - t2, 3),
        "build_snapshot_seconds": round(t4 - t3, 3),
        "total_seconds": round(t4 - t0, 3),
    }
    return manifest, documents, scope, timing


def probe(root: Path, revision: str | None = None) -> dict:
    if revision:
        revision_source = "argv"
    else:
        revision = rp.read_git_revision(root)
        revision_source = "git-head" if revision else "fallback"
        if not revision:
            revision = "unknown-revision"

    build_a, _, _, timing_a = _timed_build(root, revision)
    build_b, docs_b, scope_b, timing_b = _timed_build(root, revision)
    baseline = build_b["snapshot_digest"]

    # independence: a different spelling of the same root
    spelled = root / rp.CODE_ROOTS[0] / ".."
    alt_root = spelled if spelled.is_dir() else root
    alt_manifest, _, _, _ = _timed_build(alt_root, revision)
    alt_spelling = alt_manifest["snapshot_digest"]

    # independence: shuffled element order
    shuffled = _clone(docs_b)
    rng = random.Random(SHUFFLE_SEED)
    for doc in shuffled:
        rng.shuffle(doc["nodes"])
        rng.shuffle(doc["edges"])
    shuffled_digest = _digest_of(shuffled, scope_b)

    # independence: JSON round trip through the canonical form
    round_trip = [json.loads(canonical_bytes(doc).decode("utf-8")) for doc in docs_b]
    round_trip_digest = _digest_of(round_trip, scope_b)

    sensitivity = _run_mutations(FIELD_MUTATIONS, docs_b, scope_b, baseline)
    structure = _run_mutations(STRUCTURE_MUTATIONS, docs_b, scope_b, baseline)

    refusals = []
    for label, case in REFUSAL_CASES:
        docs, scope = case(_clone(docs_b), _clone(scope_b))
        code = _refusal(docs, scope)
        refusals.append({"case": label, "code": code, "refused": code != "NOT_REFUSED"})

    canonical_sizes = {doc["plane"]: len(canonical_bytes(doc)) for doc in docs_b}
    digest_text = json.dumps(build_a, sort_keys=True)
    return {
        "schema": "forest-v2-s05-replay-identity-probe/2",
        "read_only": True,
        "revision": revision,
        "revision_source": revision_source,
        "revision_binding": build_a["revision_binding"],
        "replay": {
            "digest_build_1": build_a["snapshot_digest"],
            "digest_build_2": baseline,
            "identical": build_a["snapshot_digest"] == baseline,
            "manifest_identical": digest_text == json.dumps(build_b, sort_keys=True),
            "phases_build_1": timing_a,
            "phases_build_2": timing_b,
        },
        "independence": {
            "alt_root_spelling": {
                "root": str(alt_root) != str(root),
                "digest": alt_spelling,
                "identical": alt_spelling == baseline,
            },
            "shuffled_order": {
                "digest": shuffled_digest,
                "identical": shuffled_digest == baseline,
            },
            "json_round_trip": {
                "digest": round_trip_digest,
                "identical": round_trip_digest == baseline,
            },
        },
        "planes": build_a["planes"],
        "scope": build_a["scope"],
        "node_total": build_a["node_total"],
        "edge_total": build_a["edge_total"],
        "canonical_bytes_per_plane": canonical_sizes,
        "canonical_bytes_total": sum(canonical_sizes.values()),
        "field_sensitivity": sensitivity,
        "field_sensitivity_as_expected": sum(1 for s in sensitivity if s["as_expected"]),
        "field_sensitivity_skipped": sum(
            1 for s in sensitivity if s["observed"].startswith("skipped:")
        ),
        "field_sensitivity_cases": len(sensitivity),
        "structure_sensitivity": structure,
        "structure_sensitivity_as_expected": sum(1 for s in structure if s["as_expected"]),
        "structure_sensitivity_cases": len(structure),
        "refusal_matrix": refusals,
        "refusals_correct": sum(1 for r in refusals if r["code"] == r["case"]),
        "refusal_cases": len(refusals),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path(__file__).resolve().parents[3]
    # An explicit revision label separates content drift from HEAD movement:
    # with the same label, the digest moves only when the scanned tree moves.
    revision = args[1] if len(args) > 1 else None
    print(json.dumps(probe(root, revision), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
