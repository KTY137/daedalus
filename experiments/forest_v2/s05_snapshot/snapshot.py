"""EXPERIMENT s05: revision-atomic four-plane snapshot builder.

Frozen frame (see ``experiments/forest_v2/README.md``): pure stdlib, read-only
over the source tree, no repository imports, no network, no subprocess, no
writes outside a caller-supplied buffer.  Nothing in ``daedalus/`` may import
this module; it is Gate-2 prework, not a production path.

What it does
------------
It takes four plane extractions of ONE source revision, refuses the build if
the set is not complete, not consistent, or not backed by matching source
evidence, and reduces the result to one content-addressed digest.  Master plan
invariant 6 ("atomic revisions"): partial graph states must not masquerade as a
revision.  Here the refusal is mechanical, not a review convention.

Why revision identity is not a string
-------------------------------------
Contract ``/1`` bound the four planes together by STRING EQUALITY of their
``revision`` field.  That was refuted on 2026-08-18: a worktree mutated BETWEEN
two plane extractions still digested as one "atomic" revision, because a label
is a claim, not evidence.  Contract ``/2`` replaces the claim with evidence in
two independent layers:

1. **Per-plane witness.**  Every extractor records ``{source path: digest of
   the exact text it consumed}``.  The witness is produced BY the read that fed
   extraction, not by a second read, so there is no window between "the bytes
   that became nodes" and "the bytes that were witnessed".  Two planes that
   read the same file must witness the same digest (``witness_conflict``), and
   every node locator must point at a file its own plane witnessed
   (``unwitnessed_locator``).
2. **Scope bracket.**  The caller scans the declared snapshot scope before the
   first extraction and again after the last, and hands both to the builder.
   Opening and closing state must be equal (``scope_drift``), and every witness
   entry must equal the bracketed state of that file
   (``witness_scope_mismatch``).

Layer 1 alone misses a file only one plane reads; layer 2 alone misses a
mutation that is reverted before the closing scan.  Together they refuse both:
what survives is a set of planes that provably read one tree state.  What is
NOT covered, stated plainly: a file mutated and reverted inside the window
while no plane read the mutated bytes -- in that case no plane's content
depends on the transient state, so the snapshot is still a function of the
bracketed tree.

Digest algebra (domain-separated, order-independent, path-independent)::

    node_digest     = sha256( canonical(node) )
    edge_digest     = sha256( canonical(edge) )
    plane_digest    = sha256( "forest-v2-plane/2" | plane | revision
                              | sorted(node_digests) | sorted(edge_digests)
                              | sorted("path=witness_digest") )
    snapshot_digest = sha256( "forest-v2-snapshot/2" | contract | revision
                              | "plane=plane_digest" for the four fixed planes )

The witness is inside the plane digest on purpose.  Without it the digest is a
function of the extracted *view* only, so a source change no extractor happens
to look at (a function body, when the extractor sees only names and spans)
leaves the digest of a "revision-atomic snapshot" unmoved.  With it, the digest
commits to the bytes each plane read.

The scope bracket is deliberately NOT in the digest: it is evidence about the
build, not content of the snapshot.  A file inside the scope that no plane
reads must not change the identity of what was extracted.

Only contract keys enter a digest.  An unknown key is a refusal, not a silently
ignored field -- otherwise a producer could smuggle a wall clock or an absolute
path into the digested content and replay identity would quietly die.

Honest caveat: ``attrs`` is free-form per plane, so this module cannot *prove*
a producer put nothing nondeterministic in there.  It can only expose it -- the
double-build check in ``probe_replay_identity.py`` is what actually catches it.
Second honest caveat: witnesses and scope entries are self-reported by the
producer.  They defeat a racing writer, not a lying extractor; a forged
document can forge its own evidence.  Sealing that needs a trusted reader
outside the producer, which this experiment does not build.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

CONTRACT = "forest-v2-plane-extraction/2"
SNAPSHOT_SCHEMA = "forest-v2-snapshot/2"
PLANE_DIGEST_DOMAIN = "forest-v2-plane/2"
SNAPSHOT_DIGEST_DOMAIN = "forest-v2-snapshot/2"
SCOPE_SCHEMA = "forest-v2-scope/1"

#: The four planes of master plan section 5, in fixed digest order.
PLANES = ("code", "type", "data", "knowledge")

_DOC_KEYS = frozenset(
    {"schema", "plane", "revision", "producer", "nodes", "edges", "witness"}
)
_NODE_KEYS = ("id", "kind", "locator", "attrs")
_EDGE_KEYS = ("src", "dst", "kind", "attrs")
_LOCATOR_KEYS = ("path", "start_line", "end_line")
_SCOPE_KEYS = ("roots", "opened", "closed")

_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = len(_DIGEST_PREFIX) + 64
_HEX = frozenset("0123456789abcdef")


class ContractError(ValueError):
    """A plane extraction or a snapshot build was refused.

    ``code`` is the machine-readable refusal reason; the probe counts them.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------
# canonical form
# --------------------------------------------------------------------------


def canonical_bytes(obj: Any) -> bytes:
    """Serialize ``obj`` to the one byte string this experiment digests.

    Sorted keys, no insignificant whitespace, UTF-8, no ASCII escaping.  Two
    equal objects always produce equal bytes regardless of insertion order.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_object(obj: Any) -> str:
    return digest_bytes(canonical_bytes(obj))


# --------------------------------------------------------------------------
# contract validation
# --------------------------------------------------------------------------


def _require_mapping(value: Any, code: str, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(code, f"{what} must be an object, got {type(value).__name__}")
    return value


def _check_source_path(path: Any, where: str, code: str) -> str:
    """The one rule set for every source path: locators AND witness/scope keys.

    Shared on purpose -- a witness key and a locator have to be comparable as
    strings, so they must be normalized by the same rules or the comparison
    silently stops matching.
    """
    if not isinstance(path, str) or not path:
        raise ContractError(code, f"source path of {where} must be a non-empty string")
    if "\\" in path:
        raise ContractError(code, f"source path of {where} is not posix: {path!r}")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise ContractError("absolute_locator", f"source path of {where} is absolute: {path!r}")
    if ".." in path.split("/"):
        raise ContractError(code, f"source path of {where} escapes the root: {path!r}")
    return path


def _check_digest(value: Any, where: str, code: str) -> str:
    if not isinstance(value, str) or len(value) != _DIGEST_LENGTH:
        raise ContractError(code, f"{where} must be a {_DIGEST_PREFIX}<64 hex> digest")
    if not value.startswith(_DIGEST_PREFIX) or not set(value[len(_DIGEST_PREFIX):]) <= _HEX:
        raise ContractError(code, f"{where} is not a lowercase {_DIGEST_PREFIX} digest: {value!r}")
    return value


def _normalize_digest_map(raw: Any, where: str, code: str) -> dict[str, str]:
    """Validate a ``{source path: content digest}`` mapping (witness or scope)."""
    mapping = _require_mapping(raw, code, where)
    out: dict[str, str] = {}
    for path, digest in mapping.items():
        clean = _check_source_path(path, where, code)
        out[clean] = _check_digest(digest, f"{where} entry {clean!r}", code)
    return out


def _normalize_locator(raw: Any, where: str) -> dict[str, Any]:
    loc = _require_mapping(raw, "bad_locator", f"locator of {where}")
    unknown = set(loc) - set(_LOCATOR_KEYS)
    if unknown:
        raise ContractError("unknown_key", f"locator of {where} has {sorted(unknown)}")
    missing = [k for k in _LOCATOR_KEYS if k not in loc]
    if missing:
        raise ContractError("bad_locator", f"locator of {where} lacks {missing}")
    path = _check_source_path(loc["path"], f"locator of {where}", "bad_locator")
    lines = []
    for key in ("start_line", "end_line"):
        value = loc[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ContractError("bad_locator", f"{key} of {where} must be a non-negative int")
        lines.append(value)
    if lines[1] < lines[0]:
        raise ContractError("bad_locator", f"end_line < start_line for {where}")
    return {"path": path, "start_line": lines[0], "end_line": lines[1]}


def _normalize_attrs(raw: Any, where: str) -> dict[str, Any]:
    attrs = _require_mapping(raw, "bad_attrs", f"attrs of {where}")
    for key in attrs:
        if not isinstance(key, str):
            raise ContractError("bad_attrs", f"attrs of {where} has a non-string key")
    try:
        canonical_bytes(attrs)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ContractError("bad_attrs", f"attrs of {where} is not JSON serializable: {exc}")
    return dict(attrs)


def _normalize_node(raw: Any, plane: str) -> dict[str, Any]:
    node = _require_mapping(raw, "bad_node", f"node of plane {plane}")
    unknown = set(node) - set(_NODE_KEYS)
    if unknown:
        raise ContractError("unknown_key", f"node of plane {plane} has {sorted(unknown)}")
    missing = [k for k in _NODE_KEYS if k not in node]
    if missing:
        raise ContractError("bad_node", f"node of plane {plane} lacks {missing}")
    node_id = node["id"]
    if not isinstance(node_id, str) or not node_id:
        raise ContractError("bad_node", f"node id of plane {plane} must be a non-empty string")
    kind = node["kind"]
    if not isinstance(kind, str) or not kind:
        raise ContractError("bad_node", f"node {node_id!r} needs a non-empty kind")
    return {
        "id": node_id,
        "kind": kind,
        "locator": _normalize_locator(node["locator"], f"node {node_id!r}"),
        "attrs": _normalize_attrs(node["attrs"], f"node {node_id!r}"),
    }


def _normalize_edge(raw: Any, plane: str) -> dict[str, Any]:
    edge = _require_mapping(raw, "bad_edge", f"edge of plane {plane}")
    unknown = set(edge) - set(_EDGE_KEYS)
    if unknown:
        raise ContractError("unknown_key", f"edge of plane {plane} has {sorted(unknown)}")
    missing = [k for k in _EDGE_KEYS if k not in edge]
    if missing:
        raise ContractError("bad_edge", f"edge of plane {plane} lacks {missing}")
    for key in ("src", "dst", "kind"):
        value = edge[key]
        if not isinstance(value, str) or not value:
            raise ContractError("bad_edge", f"edge {key} of plane {plane} must be a non-empty string")
    return {
        "src": edge["src"],
        "dst": edge["dst"],
        "kind": edge["kind"],
        "attrs": _normalize_attrs(edge["attrs"], f"edge {edge['src']}->{edge['dst']}"),
    }


def normalize_plane_document(raw: Any) -> dict[str, Any]:
    """Validate one plane extraction and return its normalized form.

    Intra-plane structure only.  Edge endpoints are checked in
    :func:`build_snapshot`, because only there is it decidable whether a
    dangling endpoint is a typo (``dangling_edge``) or an unverified
    cross-plane claim (``cross_plane_edge``), which master plan section 6
    reserves for a verifier this experiment does not build.
    """
    doc = _require_mapping(raw, "bad_document", "plane document")
    unknown = set(doc) - _DOC_KEYS
    if unknown:
        raise ContractError("unknown_key", f"plane document has {sorted(unknown)}")
    missing = [k for k in sorted(_DOC_KEYS) if k not in doc]
    if missing:
        raise ContractError("bad_document", f"plane document lacks {missing}")
    if doc["schema"] != CONTRACT:
        raise ContractError("bad_schema", f"expected {CONTRACT}, got {doc['schema']!r}")
    plane = doc["plane"]
    if plane not in PLANES:
        raise ContractError("unknown_plane", f"{plane!r} is not one of {list(PLANES)}")
    revision = doc["revision"]
    if not isinstance(revision, str) or not revision:
        raise ContractError("bad_revision", f"plane {plane} has an empty revision")
    producer = doc["producer"]
    if not isinstance(producer, str) or not producer:
        raise ContractError("bad_document", f"plane {plane} has an empty producer")
    for key in ("nodes", "edges"):
        if not isinstance(doc[key], list):
            raise ContractError("bad_document", f"plane {plane} {key} must be a list")

    nodes = [_normalize_node(n, plane) for n in doc["nodes"]]
    seen: set[str] = set()
    for node in nodes:
        if node["id"] in seen:
            raise ContractError("duplicate_node_id", f"plane {plane} repeats {node['id']!r}")
        seen.add(node["id"])
    edges = [_normalize_edge(e, plane) for e in doc["edges"]]

    witness = _normalize_digest_map(doc["witness"], f"witness of plane {plane}", "bad_witness")
    if nodes and not witness:
        raise ContractError(
            "nodes_without_witness",
            f"plane {plane} claims {len(nodes)} nodes but witnessed no source file",
        )
    unwitnessed = sorted({n["locator"]["path"] for n in nodes} - set(witness))
    if unwitnessed:
        raise ContractError(
            "unwitnessed_locator",
            f"plane {plane} locates nodes in {unwitnessed[:3]} but never witnessed reading them",
        )

    return {
        "schema": CONTRACT,
        "plane": plane,
        "revision": revision,
        "producer": producer,
        "nodes": nodes,
        "edges": edges,
        "witness": witness,
    }


# --------------------------------------------------------------------------
# digests
# --------------------------------------------------------------------------


def plane_digest(document: Mapping[str, Any]) -> str:
    """Digest one normalized plane document, independent of element order.

    The witness is part of it: a plane digest has to commit to the source bytes
    the plane read, otherwise a source change the extractor does not look at
    leaves the "revision-atomic" digest unmoved.
    """
    node_digests = sorted(digest_object(n) for n in document["nodes"])
    edge_digests = sorted(digest_object(e) for e in document["edges"])
    witness_lines = sorted(f"{path}={d}" for path, d in document["witness"].items())
    parts = [
        PLANE_DIGEST_DOMAIN,
        document["plane"],
        document["revision"],
        "nodes",
        *node_digests,
        "edges",
        *edge_digests,
        "witness",
        *witness_lines,
    ]
    return digest_bytes("\n".join(parts).encode("utf-8"))


def normalize_scope(raw: Any) -> dict[str, Any]:
    """Validate the scope bracket: the tree state before and after extraction."""
    scope = _require_mapping(raw, "bad_scope", "scope")
    unknown = set(scope) - set(_SCOPE_KEYS)
    if unknown:
        raise ContractError("unknown_key", f"scope has {sorted(unknown)}")
    missing = [k for k in _SCOPE_KEYS if k not in scope]
    if missing:
        raise ContractError("bad_scope", f"scope lacks {missing}")
    roots = scope["roots"]
    if not isinstance(roots, list) or not roots:
        raise ContractError("bad_scope", "scope roots must be a non-empty list")
    for root in roots:
        if not isinstance(root, str) or not root:
            raise ContractError("bad_scope", "scope roots must be non-empty strings")
    return {
        "roots": sorted(roots),
        "opened": _normalize_digest_map(scope["opened"], "scope opened", "bad_scope"),
        "closed": _normalize_digest_map(scope["closed"], "scope closed", "bad_scope"),
    }


def scope_digest(scope: Mapping[str, Any]) -> str:
    """Digest the bracketed tree state.  Provenance only -- not snapshot identity."""
    parts = [SCOPE_SCHEMA, "roots", *scope["roots"], "files"]
    parts.extend(f"{path}={d}" for path, d in sorted(scope["opened"].items()))
    return digest_bytes("\n".join(parts).encode("utf-8"))


def snapshot_digest(revision: str, plane_digests: Mapping[str, str]) -> str:
    """Digest the four plane digests bound to one revision."""
    missing = [p for p in PLANES if p not in plane_digests]
    if missing:
        raise ContractError("missing_plane", f"snapshot lacks planes {missing}")
    parts = [SNAPSHOT_DIGEST_DOMAIN, CONTRACT, revision]
    parts.extend(f"{plane}={plane_digests[plane]}" for plane in PLANES)
    return digest_bytes("\n".join(parts).encode("utf-8"))


# --------------------------------------------------------------------------
# the builder
# --------------------------------------------------------------------------


def _refuse_scope_drift(scope: Mapping[str, Any]) -> None:
    """The tree must look the same after the last extraction as before the first."""
    opened, closed = scope["opened"], scope["closed"]
    if opened == closed:
        return
    added = sorted(set(closed) - set(opened))
    removed = sorted(set(opened) - set(closed))
    changed = sorted(p for p in set(opened) & set(closed) if opened[p] != closed[p])
    raise ContractError(
        "scope_drift",
        "the tree moved during extraction: "
        f"changed={changed[:3]} added={added[:3]} removed={removed[:3]} "
        "-- the four planes did not see one tree state",
    )


def _refuse_witness_conflict(by_plane: Mapping[str, Mapping[str, Any]]) -> None:
    """Two planes that read the same file must have read the same bytes."""
    seen: dict[str, tuple[str, str]] = {}
    for plane in PLANES:
        for path, digest in sorted(by_plane[plane]["witness"].items()):
            if path not in seen:
                seen[path] = (plane, digest)
                continue
            other_plane, other_digest = seen[path]
            if other_digest != digest:
                raise ContractError(
                    "witness_conflict",
                    f"planes {other_plane} and {plane} read different content for "
                    f"{path!r} ({other_digest} vs {digest}) -- they extracted two "
                    "different tree states, not one revision",
                )


def _refuse_witness_scope_mismatch(
    by_plane: Mapping[str, Mapping[str, Any]], scope: Mapping[str, Any]
) -> None:
    """Every file a plane read must match the bracketed state of that file.

    This is what catches a mutation that was reverted before the closing scan:
    the bracket agrees with itself, but a plane witnessed bytes that were never
    in the bracketed tree.
    """
    opened = scope["opened"]
    for plane in PLANES:
        for path, digest in sorted(by_plane[plane]["witness"].items()):
            if path not in opened:
                raise ContractError(
                    "witness_outside_scope",
                    f"plane {plane} read {path!r}, which the declared scope "
                    f"{scope['roots']} does not cover -- unbracketed input",
                )
            if opened[path] != digest:
                raise ContractError(
                    "witness_scope_mismatch",
                    f"plane {plane} read {path!r} as {digest} but the bracketed tree "
                    f"holds {opened[path]} -- the file moved and moved back",
                )


def build_snapshot(documents: Iterable[Any], scope: Any) -> dict[str, Any]:
    """Bind four plane extractions to one revision and content-address them.

    ``scope`` is the mandatory atomicity evidence: ``{"roots": [...],
    "opened": {path: digest}, "closed": {path: digest}}``, scanned by the
    caller before the first extraction and after the last one.  It is not
    optional and has no default -- an opt-in atomicity gate is not a gate.

    Refuses (``ContractError``) on: an incomplete plane set, a repeated plane,
    a revision label that differs between planes, a tree that moved during
    extraction, two planes that read different bytes of the same file, a plane
    that read outside the declared scope or read bytes the bracket never held,
    any contract violation, an edge endpoint missing from its own plane, and an
    edge reaching into another plane.  There is no partial result -- a refusal
    returns no digest at all.
    """
    by_plane: dict[str, dict[str, Any]] = {}
    for raw in documents:
        doc = normalize_plane_document(raw)
        plane = doc["plane"]
        if plane in by_plane:
            raise ContractError("duplicate_plane", f"plane {plane} supplied twice")
        by_plane[plane] = doc

    missing = [p for p in PLANES if p not in by_plane]
    if missing:
        raise ContractError("missing_plane", f"snapshot lacks planes {missing}")

    revisions = {doc["revision"] for doc in by_plane.values()}
    if len(revisions) != 1:
        detail = ", ".join(
            f"{plane}={by_plane[plane]['revision']}" for plane in PLANES
        )
        raise ContractError("revision_mismatch", f"planes disagree: {detail}")
    revision = revisions.pop()

    # Atomicity, in evidence order: the tree-level bracket first (it is the
    # claim about the whole window), then the per-plane source evidence.
    checked_scope = normalize_scope(scope)
    _refuse_scope_drift(checked_scope)
    _refuse_witness_conflict(by_plane)
    _refuse_witness_scope_mismatch(by_plane, checked_scope)

    ids_by_plane = {plane: {n["id"] for n in doc["nodes"]} for plane, doc in by_plane.items()}
    for plane in PLANES:
        own = ids_by_plane[plane]
        for edge in by_plane[plane]["edges"]:
            for endpoint in (edge["src"], edge["dst"]):
                if endpoint in own:
                    continue
                foreign = [p for p in PLANES if p != plane and endpoint in ids_by_plane[p]]
                if foreign:
                    raise ContractError(
                        "cross_plane_edge",
                        f"plane {plane} edge {edge['src']}->{edge['dst']} reaches {foreign[0]}; "
                        "cross-plane relations need a verifier, not an extractor",
                    )
                raise ContractError(
                    "dangling_edge",
                    f"plane {plane} edge {edge['src']}->{edge['dst']} has unknown endpoint {endpoint!r}",
                )

    digests = {plane: plane_digest(by_plane[plane]) for plane in PLANES}
    manifest_planes = {
        plane: {
            "digest": digests[plane],
            "producer": by_plane[plane]["producer"],
            "nodes": len(by_plane[plane]["nodes"]),
            "edges": len(by_plane[plane]["edges"]),
            "witness_files": len(by_plane[plane]["witness"]),
        }
        for plane in PLANES
    }
    witnessed = set()
    for plane in PLANES:
        witnessed |= set(by_plane[plane]["witness"])
    return {
        "schema": SNAPSHOT_SCHEMA,
        "contract": CONTRACT,
        "revision": revision,
        "revision_binding": "source-evidence",
        "snapshot_digest": snapshot_digest(revision, digests),
        "planes": manifest_planes,
        "node_total": sum(p["nodes"] for p in manifest_planes.values()),
        "edge_total": sum(p["edges"] for p in manifest_planes.values()),
        "scope": {
            "digest": scope_digest(checked_scope),
            "roots": checked_scope["roots"],
            "files": len(checked_scope["opened"]),
            "witnessed_files": len(witnessed),
            "unread_files": len(set(checked_scope["opened"]) - witnessed),
        },
    }


def load_plane_documents(paths: Iterable[Any]) -> list[dict[str, Any]]:
    """Read plane extractions from JSON files (read-only)."""
    docs = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            docs.append(json.load(handle))
    return docs


def main(argv: list[str] | None = None) -> int:
    """Read a scope file and four plane JSON files, print the manifest.  No writes."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 5:
        print(
            json.dumps(
                {
                    "schema": SNAPSHOT_SCHEMA,
                    "usage": "python snapshot.py <scope.json> <plane.json> "
                    "<plane.json> <plane.json> <plane.json>",
                    "scope": "{roots: [...], opened: {path: digest}, closed: {...}} "
                    "-- scanned before the first and after the last extraction",
                    "planes": list(PLANES),
                    "contract": CONTRACT,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    try:
        scope = load_plane_documents(args[:1])[0]
        manifest = build_snapshot(load_plane_documents(args[1:]), scope)
    except ContractError as exc:
        print(json.dumps({"refused": exc.code, "detail": exc.detail}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
