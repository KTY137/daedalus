"""EXPERIMENT s05: revision-atomic four-plane snapshot builder.

Frozen frame (see ``experiments/forest_v2/README.md``): pure stdlib, read-only
over the source tree, no repository imports, no network, no subprocess, no
writes outside a caller-supplied buffer.  Nothing in ``daedalus/`` may import
this module; it is Gate-2 prework, not a production path.

What it does
------------
It takes four plane extractions that each claim the SAME source revision,
refuses the build if the set is not complete and consistent, and reduces the
result to one content-addressed digest.  Master plan invariant 6 ("atomic
revisions"): partial graph states must not masquerade as a revision.  Here the
refusal is mechanical, not a review convention.

Digest algebra (domain-separated, order-independent, path-independent)::

    node_digest     = sha256( canonical(node) )
    edge_digest     = sha256( canonical(edge) )
    plane_digest    = sha256( "forest-v2-plane/1" | plane | revision
                              | sorted(node_digests) | sorted(edge_digests) )
    snapshot_digest = sha256( "forest-v2-snapshot/1" | contract | revision
                              | "plane=plane_digest" for the four fixed planes )

Only contract keys enter a digest.  An unknown key is a refusal, not a silently
ignored field -- otherwise a producer could smuggle a wall clock or an absolute
path into the digested content and replay identity would quietly die.

Honest caveat: ``attrs`` is free-form per plane, so this module cannot *prove*
a producer put nothing nondeterministic in there.  It can only expose it -- the
double-build check in ``probe_replay_identity.py`` is what actually catches it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

CONTRACT = "forest-v2-plane-extraction/1"
SNAPSHOT_SCHEMA = "forest-v2-snapshot/1"
PLANE_DIGEST_DOMAIN = "forest-v2-plane/1"
SNAPSHOT_DIGEST_DOMAIN = "forest-v2-snapshot/1"

#: The four planes of master plan section 5, in fixed digest order.
PLANES = ("code", "type", "data", "knowledge")

_DOC_KEYS = frozenset({"schema", "plane", "revision", "producer", "nodes", "edges"})
_NODE_KEYS = ("id", "kind", "locator", "attrs")
_EDGE_KEYS = ("src", "dst", "kind", "attrs")
_LOCATOR_KEYS = ("path", "start_line", "end_line")


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


def _normalize_locator(raw: Any, where: str) -> dict[str, Any]:
    loc = _require_mapping(raw, "bad_locator", f"locator of {where}")
    unknown = set(loc) - set(_LOCATOR_KEYS)
    if unknown:
        raise ContractError("unknown_key", f"locator of {where} has {sorted(unknown)}")
    missing = [k for k in _LOCATOR_KEYS if k not in loc]
    if missing:
        raise ContractError("bad_locator", f"locator of {where} lacks {missing}")
    path = loc["path"]
    if not isinstance(path, str) or not path:
        raise ContractError("bad_locator", f"locator path of {where} must be a non-empty string")
    if "\\" in path:
        raise ContractError("bad_locator", f"locator path of {where} is not posix: {path!r}")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise ContractError("absolute_locator", f"locator path of {where} is absolute: {path!r}")
    if ".." in path.split("/"):
        raise ContractError("bad_locator", f"locator path of {where} escapes the root: {path!r}")
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
    return {
        "schema": CONTRACT,
        "plane": plane,
        "revision": revision,
        "producer": producer,
        "nodes": nodes,
        "edges": edges,
    }


# --------------------------------------------------------------------------
# digests
# --------------------------------------------------------------------------


def plane_digest(document: Mapping[str, Any]) -> str:
    """Digest one normalized plane document, independent of element order."""
    node_digests = sorted(digest_object(n) for n in document["nodes"])
    edge_digests = sorted(digest_object(e) for e in document["edges"])
    parts = [
        PLANE_DIGEST_DOMAIN,
        document["plane"],
        document["revision"],
        "nodes",
        *node_digests,
        "edges",
        *edge_digests,
    ]
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


def build_snapshot(documents: Iterable[Any]) -> dict[str, Any]:
    """Bind four plane extractions to one revision and content-address them.

    Refuses (``ContractError``) on: an incomplete plane set, a repeated plane,
    a revision that differs between planes, any contract violation, an edge
    endpoint missing from its own plane, and an edge that reaches into another
    plane.  There is no partial result -- a refusal returns no digest at all.
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
        }
        for plane in PLANES
    }
    return {
        "schema": SNAPSHOT_SCHEMA,
        "contract": CONTRACT,
        "revision": revision,
        "snapshot_digest": snapshot_digest(revision, digests),
        "planes": manifest_planes,
        "node_total": sum(p["nodes"] for p in manifest_planes.values()),
        "edge_total": sum(p["edges"] for p in manifest_planes.values()),
    }


def load_plane_documents(paths: Iterable[Any]) -> list[dict[str, Any]]:
    """Read plane extractions from JSON files (read-only)."""
    docs = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            docs.append(json.load(handle))
    return docs


def main(argv: list[str] | None = None) -> int:
    """Read four plane JSON files, print the snapshot manifest.  No writes."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            json.dumps(
                {
                    "schema": SNAPSHOT_SCHEMA,
                    "usage": "python snapshot.py <plane.json> <plane.json> "
                    "<plane.json> <plane.json>",
                    "planes": list(PLANES),
                    "contract": CONTRACT,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    try:
        manifest = build_snapshot(load_plane_documents(args))
    except ContractError as exc:
        print(json.dumps({"refused": exc.code, "detail": exc.detail}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
