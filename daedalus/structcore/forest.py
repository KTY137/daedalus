"""Deterministic, domain-neutral Code-Knowledge Forest snapshots.

The "forest" is a product metaphor, not a claim that software is an acyclic
tree.  A repository contains cycles, relations with different meanings, and
groups that cannot be represented faithfully as pairwise edges.  This module
therefore exposes a multiplex graph with explicit hyperedges:

* nodes are indexed source files, and -- when the index carries them --
  DOCUMENTS and TYPES/FIELDS, which are the same contract with a different
  ``kind``;
* edge layers keep imports, document links, type structure and temporal
  co-change evidence separate;
* hyperedges preserve clone groups without expanding them into fake cliques.

Symbols, build targets, schemas, runtime spans, and domain entities can be
added as new node kinds and relation layers without changing this contract --
``document`` (node kind) and ``documents`` (relation layer) were added exactly
that way, and ``type``/``field`` were added the same way again, and all three
cost this file no new field, no new dataclass and no schema bump.
No latent coordinates or partitions are inferred here.  The snapshot is
evidence-preserving input for later, independently evaluated algorithms.

NOT EVERY NODE KIND IS A FILE, AND THAT ASYMMETRY IS THE POINT
--------------------------------------------------------------
``document`` joined ``dss.FILE_NODE_KINDS``; ``type`` and ``field`` deliberately
did NOT, and a future reader must not "finish the job" by adding them.  The
difference is not taste, it is arithmetic:

* A document has BYTES ON DISK.  It can be a hierarchy leaf, a selection seed
  and a candidate for a token budget, because ``n_tokens`` is a measurement of
  it.  A ``type`` node is a DERIVED assertion about a region of a file that is
  already a node in its own right; it has no bytes of its own.  Pack it and
  ``dss._estimated_tokens`` falls through to its ``loc * 8`` fallback and
  invents a cost for something that cannot be read into a prompt -- the token
  accounting stops being accounting and becomes fiction, while the file that
  actually contains the declaration may be omitted for lack of budget.  So a
  type node is EVIDENCE THAT RE-SCORES FILE NODES, never a packable item.
* The same asymmetry holds for the safety fence.  ``graph.fenced_dominance``
  divides by ``graph._graph_nodes``, which is fed by ``index["modules"]`` and
  ``index["import_edges"]``.  Type nodes have no forward imports, so every one
  of them would land in the denominator and none in the numerator: ``fraction``
  falls, ``provider_router``'s reachability stand-down stops firing, and every
  task stays on the premium lane.  That is real money spent for a wrong reason,
  which is why the type layer lives in ``type_nodes``/``type_edges`` and never
  in ``modules`` or ``import_edges``.  This file honours that by keeping
  ``module_ids`` (the membership gate of four other layers) closed to them.
* And the type relations are a LENS, not a diffusion channel.  The fan-in of
  ``Path``/``dict``/``str`` in this repo was MEASURED before the layer was
  built: uncapped, "two functions that mention the same type are two hops
  apart" makes 53.6% of all function pairs adjacent, i.e. the graph is
  effectively complete.  So ``dss._relation_adjacencies`` filters diffusion to
  file-kind endpoints; these layers are published for consumers that ask about
  them by name, and the hub cap that would make them diffusible is measured and
  reported in ``index["types"]["coverage"]``, not assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "daedalus-forest/1"


def _json_value(value: Any) -> Any:
    """Return a deterministic JSON-compatible value."""
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


@dataclass(frozen=True)
class ForestNode:
    id: str
    kind: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "attributes": _json_value(self.attributes),
        }


@dataclass(frozen=True)
class ForestEdge:
    source: str
    target: str
    relation: str
    directed: bool
    weight: float = 1.0
    evidence: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "directed": self.directed,
            "weight": self.weight,
            "evidence": list(self.evidence),
            "attributes": _json_value(self.attributes),
        }


@dataclass(frozen=True)
class ForestHyperedge:
    id: str
    relation: str
    members: tuple[str, ...]
    weight: float = 1.0
    evidence: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "relation": self.relation,
            "members": list(self.members),
            "weight": self.weight,
            "evidence": list(self.evidence),
            "attributes": _json_value(self.attributes),
        }


@dataclass(frozen=True)
class KnowledgeForest:
    """A deterministic evidence snapshot, suitable for storage and comparison."""

    root: str
    nodes: tuple[ForestNode, ...]
    edges: tuple[ForestEdge, ...]
    hyperedges: tuple[ForestHyperedge, ...]
    provenance: Mapping[str, Any]
    schema: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "root": self.root,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "hyperedges": [edge.to_dict() for edge in self.hyperedges],
            "provenance": _json_value(self.provenance),
        }

    @property
    def content_sha256(self) -> str:
        body = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    @property
    def layer_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for edge in self.edges:
            counts[edge.relation] = counts.get(edge.relation, 0) + 1
        for edge in self.hyperedges:
            counts[edge.relation] = counts.get(edge.relation, 0) + 1
        return dict(sorted(counts.items()))


_CLONE_RELATIONS = {
    "unit_clusters": "clone_exact",
    "renamed_clusters": "clone_renamed",
    "near_clusters": "clone_near",
    "window_clusters": "clone_window",
}

# The two node kinds that are NOT files.  Kept as a literal here rather than
# imported from ``typegraph`` so this module stays a pure normaliser of an index
# dict with no dependency on the producer of one of its blocks -- the same
# reason ``document`` is a string literal below and not an import from
# ``markdown``.  ``dss.FILE_NODE_KINDS`` is the set these are held OUT of; see
# this module's docstring for why that is arithmetic and not taste.
_TYPE_NODE_KINDS = frozenset({"type", "field"})

# ``index["type_edges"]`` is a mapping keyed by relation name, and this module
# publishes whatever keys it finds -- a seventh relation (``instantiates`` is
# the planned one) then needs no edit here.  What it may NOT do is land in a
# layer that already means something else: an edge with a type endpoint filed
# under ``imports`` would be read as an import by every consumer of that layer,
# starting with the reachability the safety fence is built on.  Refuse rather
# than merge.
_RESERVED_RELATIONS = frozenset(
    {"imports", "documents", "co_change"} | set(_CLONE_RELATIONS.values())
)


def _canonical_key(value: Any) -> str:
    """A total, deterministic ordering key for an attribute mapping."""
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _is_type_node_id(node_id: str) -> bool:
    """True for an id that CANNOT be mistaken for a repo-relative path.

    Two things at once, and both are required.  The ``kind:`` prefix follows the
    ``repo:``/``dir:``/``file:`` convention already used by ``dss``'s derived
    hierarchy, and the ``#`` separator is a character no path in an indexed repo
    carries -- ``build_forest_hierarchy`` segments node ids on ``/`` and would
    otherwise happily read ``type:pkg/mod.py#Foo`` as the directory
    ``type:pkg``.  The kind filter is what actually keeps a type node out of the
    file world; this is defence in depth, and it makes a leak legible in a diff
    instead of only in a stack trace.
    """
    return node_id.startswith(("type:", "field:")) and "#" in node_id


def _hyperedge_id(
    relation: str,
    members: tuple[str, ...],
    cluster: Mapping[str, Any],
) -> str:
    identity = json.dumps(
        [relation, list(members), _json_value(cluster)],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{relation}:{hashlib.sha256(identity).hexdigest()[:16]}"


def _clone_members(cluster: Mapping[str, Any]) -> tuple[str, ...]:
    if "files" in cluster:
        members = cluster.get("files") or ()
    else:
        members = (
            site.get("module")
            for site in cluster.get("sites", ())
            if isinstance(site, Mapping)
        )
    return tuple(sorted({str(member) for member in members if member}))


def build_knowledge_forest(
    index: Mapping[str, Any],
    *,
    temporal_pairs: Iterable[Mapping[str, Any]] = (),
) -> KnowledgeForest:
    """Normalize a StructCore index and optional co-change rows.

    ``temporal_pairs`` should use ``structcore.churn.co_change_pairs`` rows.
    Missing or out-of-scope members are skipped instead of manufacturing nodes.
    Negative/zero PMI evidence is kept only in attributes; the non-negative
    edge weight is the pair's lift, which has the intuitive neutral value 1.
    """
    modules = index.get("modules") or {}
    module_ids = {str(module) for module in modules}
    heat_by_module = {
        str(row["module"]): row
        for row in index.get("module_heat", ())
        if isinstance(row, Mapping) and row.get("module") is not None
    }
    fan_in = index.get("fan_in") or {}

    nodes: list[ForestNode] = []
    for module in sorted(module_ids):
        attributes = dict(modules[module])
        heat = heat_by_module.get(module, {})
        attributes.update({
            "fan_in": int(fan_in.get(module, 0) or 0),
            "heat_score": float(heat.get("score", 0.0) or 0.0),
            "churn": int(heat.get("churn", 0) or 0),
        })
        # THE PROMISED SECOND NODE KIND. This module's own docstring already
        # said documents could be added "as new node kinds and relation layers
        # without changing this contract", and this is that, in full: one
        # discriminator read, no new field, no new dataclass, no schema bump.
        #
        # The alternative -- labelling a README "source_file" because that is
        # what the loop used to emit -- would push the lie downstream into every
        # consumer that keys off ``node.kind`` (``dss``'s hierarchy, propagation
        # set and budget packer; ``context_plan``'s latent evidence filter), and
        # those are exactly the consumers that must be able to tell prose from
        # code. ``heat_score``/``churn`` come out 0 because documents are held
        # out of ``module_heat`` upstream, which is deliberate, not missing data.
        kind = "document" if attributes.get("kind") == "document" else "source_file"
        nodes.append(ForestNode(module, kind, attributes))

    # THE THIRD AND FOURTH NODE KINDS: ``type`` and ``field``.  Same shape as
    # the document addition -- read a block the index either carries or does
    # not, one discriminator, no new field, no new dataclass, no schema bump.
    #
    # ``type_ids`` is a SEPARATE set from ``module_ids`` on purpose, and this is
    # the single most load-bearing line of the addition.  ``module_ids`` is not
    # a convenience variable: it is the membership gate of four other layers
    # (imports, document links, co-change and clone-hyperedge members).  Widen
    # it and a type node becomes eligible to be a clone-group member or an
    # import endpoint, which is a fabricated fact about the repository, not a
    # cosmetic leak.  So type nodes get their own set, and every gate below
    # names exactly the sets it accepts.
    #
    # Absent key -> empty loop -> byte-identical forest, so an index built
    # without the type layer produces the forest it always produced.
    type_ids: set[str] = set()
    type_rows = sorted(
        (row for row in (index.get("type_nodes") or ()) if isinstance(row, Mapping)),
        key=lambda row: str(row.get("id", "")),
    )
    for row in type_rows:
        node_id = str(row.get("id", ""))
        kind = str(row.get("kind", ""))
        # Three refusals, none of them redundant: a row that is not one of the
        # two type kinds is not this layer's business; an id in the namespace of
        # files would collide with a real file in ``build_forest_hierarchy``
        # (which raises on two ids mapping to one path) and is refused rather
        # than renamed; and an id outside the ``type:``/``field:`` namespace
        # cannot be told apart from a path by any downstream reader.
        if kind not in _TYPE_NODE_KINDS:
            continue
        if not _is_type_node_id(node_id) or node_id in module_ids:
            continue
        if node_id in type_ids:
            continue
        type_ids.add(node_id)
        attributes = {
            key: value for key, value in sorted(row.items())
            if key not in {"id", "kind"}
        }
        nodes.append(ForestNode(node_id, kind, attributes))

    edges: list[ForestEdge] = []
    seen_imports: set[tuple[str, str]] = set()
    for source, targets in sorted((index.get("import_edges") or {}).items()):
        for target in sorted(set(targets or ())):
            if source not in module_ids or target not in module_ids:
                continue
            key = (str(source), str(target))
            if key in seen_imports:
                continue
            seen_imports.add(key)
            edges.append(ForestEdge(
                str(source),
                str(target),
                "imports",
                True,
                evidence=("structcore.import_edges",),
            ))

    # DOCUMENT LINK LAYER. A separate relation, not extra ``imports`` edges: the
    # multiplex graph exists so two kinds of relation can coexist without either
    # one being read as the other. A link says "this document refers to that
    # file"; an import says "this code cannot run without that file". Merging
    # them would silently move ``fan_in`` and every reachability answer derived
    # from the import layer, including the safety fence's dominance fraction.
    # Absent key -> empty loop -> byte-identical forest, so an index built
    # without documents produces the forest it always produced.
    seen_links: set[tuple[str, str]] = set()
    for source, targets in sorted((index.get("document_links") or {}).items()):
        for target in sorted(set(targets or ())):
            if source not in module_ids or target not in module_ids:
                continue
            key = (str(source), str(target))
            if key in seen_links:
                continue
            seen_links.add(key)
            edges.append(ForestEdge(
                str(source),
                str(target),
                "documents",
                True,
                evidence=("structcore.document_links",),
            ))

    # TYPE STRUCTURE LAYERS.  One relation layer per relation name the index
    # publishes (``has_field``, ``field_type``, ``inherits``, ``consumes``,
    # ``produces``, ``alias_of``), because they answer different questions and
    # a multiplex graph exists precisely so they do not have to be merged into
    # one "related to" soup.
    #
    # The endpoint gate is asymmetric and that is not an oversight: a TARGET is
    # always a type-kind node, while a SOURCE may also be a file, because
    # ``consumes``/``produces`` start at a FUNCTION and functions are not forest
    # nodes -- so those two attach to the file that declares the function and
    # carry its identity in ``attributes["function_ref"]``.  Anything else is
    # dropped in silence rather than manufactured: an edge to a type node the
    # index did not publish is missing evidence, and inventing the endpoint
    # would make the forest disagree with the index it was normalised from.
    seen_type_edges: set[tuple[str, str, str, str]] = set()
    for relation in sorted(index.get("type_edges") or {}):
        if relation in _RESERVED_RELATIONS:
            continue
        rows = [
            row for row in ((index.get("type_edges") or {}).get(relation) or ())
            if isinstance(row, Mapping)
        ]
        for row in sorted(
            rows,
            key=lambda row: (
                str(row.get("source", "")),
                str(row.get("target", "")),
                _canonical_key(row.get("attributes") or {}),
            ),
        ):
            source = str(row.get("source", ""))
            target = str(row.get("target", ""))
            if target not in type_ids:
                continue
            if source not in module_ids and source not in type_ids:
                continue
            attributes = dict(row.get("attributes") or {})
            # Deduplicated on the FULL row, not on the pair: one function can
            # legitimately consume the same type twice through two different
            # parameters, and collapsing those two would delete the ``param``
            # evidence that makes the edge worth publishing.  Two byte-identical
            # rows, on the other hand, are one fact stated twice.
            key = (relation, source, target, _canonical_key(attributes))
            if key in seen_type_edges:
                continue
            seen_type_edges.add(key)
            edges.append(ForestEdge(
                source,
                target,
                str(relation),
                True,
                evidence=("structcore.type_edges",),
                attributes=attributes,
            ))

    seen_temporal: set[tuple[str, str]] = set()
    for pair in temporal_pairs:
        a, b = str(pair.get("a", "")), str(pair.get("b", ""))
        if not a or not b or a == b or a not in module_ids or b not in module_ids:
            continue
        a, b = sorted((a, b))
        if (a, b) in seen_temporal:
            continue
        seen_temporal.add((a, b))
        lift = max(0.0, float(pair.get("lift", 1.0) or 0.0))
        attributes = {
            key: pair[key]
            for key in (
                "count", "count_a", "count_b", "commits_considered", "pmi", "lift"
            )
            if key in pair
        }
        edges.append(ForestEdge(
            a,
            b,
            "co_change",
            False,
            weight=lift,
            evidence=("git.co_change",),
            attributes=attributes,
        ))

    hyperedges: list[ForestHyperedge] = []
    duplication = index.get("duplication") or {}
    for cluster_key, relation in _CLONE_RELATIONS.items():
        clusters = duplication.get(cluster_key) or ()
        for cluster in clusters:
            if not isinstance(cluster, Mapping):
                continue
            members = tuple(
                member for member in _clone_members(cluster)
                if member in module_ids
            )
            if len(members) < 2:
                continue
            attributes = {
                key: value
                for key, value in cluster.items()
                if key not in {"sites", "files"}
            }
            weight_value = (
                cluster.get("similarity")
                or cluster.get("shared_runs")
                or cluster.get("count")
                or 1.0
            )
            hyperedges.append(ForestHyperedge(
                id=_hyperedge_id(relation, members, cluster),
                relation=relation,
                members=members,
                weight=float(weight_value),
                evidence=(f"structcore.duplication.{cluster_key}",),
                attributes=attributes,
            ))

    edges.sort(key=lambda edge: (
        edge.relation, edge.source, edge.target, edge.directed, edge.weight
    ))
    hyperedges.sort(key=lambda edge: (edge.relation, edge.members, edge.id))
    provenance = {
        "backend": index.get("backend", {}),
        "scope_key": index.get("scope_key"),
        "ignored": index.get("ignored", {}),
        "tokenizer": index.get("tokenizer"),
        "source_schema": "structcore/index",
    }
    return KnowledgeForest(
        root=str(index.get("root", "")),
        nodes=tuple(nodes),
        edges=tuple(edges),
        hyperedges=tuple(hyperedges),
        provenance=provenance,
    )
