# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The type layer's FOREST WIRING — is it a lens, and does it stay one?

Stage 4 turns ``index["type_nodes"]``/``index["type_edges"]`` into forest nodes
of kind ``type``/``field`` and five relation layers.  Every test here is one of
four questions, and three of them are about what the layer is NOT allowed to do.

  1. IS IT THERE? The kinds and the relations appear, the ids are in a namespace
     no path can occupy, and the endpoint gate drops nothing the index published.

  2. IS IT STILL ADDITIVE? The file half of the forest -- the nodes, the import
     layer, the clone hyperedges -- is byte-identical with the layer on and off,
     and ``module_ids`` (the membership gate of four other layers) did not grow.

  3. CAN IT BE PACKED? No -- invariant I3.  ``dss.build_forest_hierarchy``
     ignores type nodes, so the hierarchy is byte-identical; and
     ``build_context_plan``, which used to validate MEMBERSHIP without KIND,
     now refuses them.  The reason is arithmetic and this file measures it
     directly: ``_estimated_tokens`` has a ``loc * 8`` fallback that CANNOT
     fail, so for a node with no bytes on disk it does not report a gap, it
     reports 8 tokens.  ``test_the_phantom_cost_this_guard_prevents_is_real``
     asks the fallback what it would have said, so the number the guard exists
     to prevent is in the record rather than in an argument.

  4. IS IT A LENS AND NOT A CHANNEL? Invariant I6.  The hub fan-in of this repo
     was MEASURED before the layer was built: uncapped, "two functions that
     mention the same type are two hops apart" makes 53.6% of all function pairs
     adjacent, ``str`` alone contributing 939,135 of them.  So
     ``dss._relation_adjacencies`` filters diffusion to file-kind endpoints, and
     ``TheLensIsNotAChannel`` proves it both by name (no channel is produced)
     and by effect (two files that consume the same type get no score from each
     other, even with ``unknown_relation_weight`` turned up).

To watch the guards go red, break exactly one at a time: add ``"type"`` to
``dss.FILE_NODE_KINDS``; delete the ``kinds[node_id] not in FILE_NODE_KINDS``
check in ``build_context_plan``; delete the ``file_ids`` filter in
``_relation_adjacencies``; or replace ``type_ids`` in ``forest.py`` with
``module_ids``.

Companion files: ``test_typegraph_parse.py`` (extraction),
``test_typegraph_resolve.py`` (resolution), ``test_typegraph_index.py`` (the
index blocks these are built from), ``test_typegraph_fixture.py`` (the
pre-feature baselines none of this may contradict).
"""
from __future__ import annotations

import copy
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import dss as dss_mod
from daedalus.structcore import typegraph as typegraph_mod
from daedalus.structcore.dss import (DEFAULT_RELATION_WEIGHTS, DSSConfig,
                                     FILE_NODE_KINDS, build_context_plan,
                                     build_forest_hierarchy,
                                     diffuse_relation_scores, restrict_scores,
                                     semantic_super_sample)
from daedalus.structcore.forest import (ForestNode, build_knowledge_forest,
                                        SCHEMA_VERSION)
from daedalus.structcore.index import build_index

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "typegraph"

# Same pinning as ``test_typegraph_index.py``, for the same reason: ``build_index``
# writes a sqlite row per file, and without this every run would read and write
# the developer's real cache.
_PINNED = ("DAEDALUS_INDEX_TYPES", "DAEDALUS_INDEX_DOCUMENTS",
           "DAEDALUS_CACHE_DIR", "DAEDALUS_NO_CACHE",
           "DAEDALUS_SCAN_MIN_PARALLEL", "DAEDALUS_SCAN_WORKERS")
_SAVED: dict[str, str | None] = {}
_TMP_CACHE: str = ""


def setUpModule() -> None:
    global _TMP_CACHE
    for name in _PINNED:
        _SAVED[name] = os.environ.get(name)
        os.environ.pop(name, None)
    _TMP_CACHE = tempfile.mkdtemp(prefix="tgforest-cache-")
    os.environ["DAEDALUS_CACHE_DIR"] = _TMP_CACHE


def tearDownModule() -> None:
    for name, value in _SAVED.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    shutil.rmtree(_TMP_CACHE, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Captured baselines (stage 3's published fixture numbers, re-asked of the      #
# forest). Never re-capture these silently: a re-capture deletes the tripwire.  #
# --------------------------------------------------------------------------- #
FILE_NODES = 16
TYPE_NODES = 23
FIELD_NODES = 45
LAYER_COUNTS = {
    "consumes": 19,
    "field_type": 4,
    "has_field": 45,
    "imports": 6,
    "inherits": 2,
    "produces": 8,
}
# ``alias_of`` is published by the index as an EMPTY list and therefore produces
# no layer at all. Named here so its absence reads as a measured zero rather
# than as a relation somebody forgot to wire.
EMPTY_RELATIONS = ("alias_of",)
# The relations whose SOURCE is a file rather than a type, because a function is
# not a forest node and its identity travels in the attributes instead.
FUNCTION_SOURCED = ("consumes", "produces")


def _build(**kw) -> dict:
    """``documents`` and ``types`` are ALWAYS explicit: both consult an env var
    when left as None, so a default would make every baseline here a fact about
    the caller's shell."""
    kw.setdefault("documents", False)
    kw.setdefault("types", False)
    return build_index(FIXTURE, **kw)


class _OnAndOff(unittest.TestCase):
    """One repo, two indexes, two forests, differing in exactly one flag."""

    @classmethod
    def setUpClass(cls):
        cls.index_off = _build(types=False)
        cls.index_on = _build(types=True)
        cls.off = build_knowledge_forest(cls.index_off)
        cls.on = build_knowledge_forest(cls.index_on)
        cls.type_ids = frozenset(
            node.id for node in cls.on.nodes if node.kind in {"type", "field"}
        )
        cls.file_ids = frozenset(
            node.id for node in cls.on.nodes if node.kind in FILE_NODE_KINDS
        )


# --------------------------------------------------------------------------- #
# 1. THE LAYER IS THERE                                                        #
# --------------------------------------------------------------------------- #
class TheForestCarriesTheLayer(_OnAndOff):

    def test_the_new_node_kinds_appear(self):
        counts: dict[str, int] = {}
        for node in self.on.nodes:
            counts[node.kind] = counts.get(node.kind, 0) + 1
        self.assertEqual(counts, {
            "source_file": FILE_NODES,
            "type": TYPE_NODES,
            "field": FIELD_NODES,
        })

    def test_the_relation_layers_appear(self):
        """Stated as the WHOLE ``layer_counts`` dict rather than as six
        membership checks, so an extra layer cannot appear unnoticed."""
        self.assertEqual(self.on.layer_counts, LAYER_COUNTS)
        for relation in EMPTY_RELATIONS:
            with self.subTest(relation=relation):
                self.assertEqual(self.index_on["type_edges"][relation], [])
                self.assertNotIn(relation, self.on.layer_counts)

    def test_no_edge_the_index_published_was_dropped(self):
        """The endpoint gate must be a guard, not a filter: everything stage 3
        published has to survive it, or the forest and the index disagree about
        what the repository contains."""
        published = sum(
            len(rows) for rows in self.index_on["type_edges"].values()
        )
        carried = sum(
            count for relation, count in self.on.layer_counts.items()
            if relation != "imports"
        )
        self.assertEqual(carried, published)

    def test_every_node_the_index_published_is_a_forest_node(self):
        self.assertEqual(
            sorted(self.type_ids),
            sorted(row["id"] for row in self.index_on["type_nodes"]),
        )

    def test_type_node_ids_cannot_be_mistaken_for_a_path(self):
        """``build_forest_hierarchy`` segments node ids on ``/`` and raises when
        two ids map to one path.  A ``kind:`` prefix alone is not enough --
        ``type:pkg/mod.py#Foo`` would read as the directory ``type:pkg`` -- so
        the ``#`` is what makes the namespace disjoint from every repo-relative
        POSIX path, and neither character may go missing."""
        for node_id in sorted(self.type_ids):
            with self.subTest(node_id=node_id):
                self.assertTrue(node_id.startswith(("type:", "field:")))
                self.assertIn("#", node_id)
                self.assertNotIn(node_id, self.index_on["modules"])
        self.assertEqual(self.type_ids & self.file_ids, frozenset())

    def test_node_attributes_carry_the_row_minus_its_identity(self):
        """id and kind become the node's own fields; everything else the index
        published stays readable as evidence."""
        by_id = {node.id: node for node in self.on.nodes}
        for row in self.index_on["type_nodes"]:
            with self.subTest(node_id=row["id"]):
                node = by_id[row["id"]]
                self.assertEqual(node.kind, row["kind"])
                self.assertEqual(
                    dict(node.attributes),
                    {k: v for k, v in row.items() if k not in {"id", "kind"}},
                )

    def test_every_type_edge_obeys_the_endpoint_gate(self):
        """Asymmetric on purpose: a target is always a type node, a source may
        be a file, because ``consumes``/``produces`` start at a FUNCTION and
        functions are not forest nodes."""
        for edge in self.on.edges:
            if edge.relation == "imports":
                continue
            with self.subTest(relation=edge.relation, source=edge.source,
                              target=edge.target):
                self.assertIn(edge.target, self.type_ids)
                self.assertIn(edge.source, self.type_ids | self.file_ids)
                self.assertEqual(edge.evidence, ("structcore.type_edges",))
                self.assertTrue(edge.directed)

    def test_function_sourced_relations_start_at_a_file_and_name_the_function(self):
        seen = set()
        for edge in self.on.edges:
            if edge.relation not in FUNCTION_SOURCED:
                continue
            seen.add(edge.relation)
            with self.subTest(relation=edge.relation, source=edge.source):
                self.assertIn(edge.source, self.file_ids)
                ref = edge.attributes["function_ref"]
                self.assertEqual(ref.split("#", 1)[0], edge.source)
        self.assertEqual(seen, set(FUNCTION_SOURCED))

    def test_declaration_relations_start_at_a_type_node(self):
        for edge in self.on.edges:
            if edge.relation not in {"has_field", "field_type", "inherits"}:
                continue
            with self.subTest(relation=edge.relation, source=edge.source):
                self.assertIn(edge.source, self.type_ids)

    def test_the_schema_was_not_bumped(self):
        """The ``document`` precedent, in full: a new node kind and new relation
        layers cost this contract no new field, no new dataclass and no schema
        bump, so a stored forest from before the layer is still readable."""
        self.assertEqual(SCHEMA_VERSION, "daedalus-forest/1")
        self.assertEqual(self.on.schema, self.off.schema)


# --------------------------------------------------------------------------- #
# 2. THE LAYER IS ADDITIVE                                                     #
# --------------------------------------------------------------------------- #
class TheFileHalfDoesNotMove(_OnAndOff):
    """Everything that was in the forest before is still exactly there.

    To watch these go red: in ``forest.py``, add the type ids to ``module_ids``
    instead of to ``type_ids``.
    """

    def test_the_file_nodes_are_byte_identical(self):
        on_files = [
            node.to_dict() for node in self.on.nodes
            if node.kind in FILE_NODE_KINDS
        ]
        self.assertEqual(on_files, [node.to_dict() for node in self.off.nodes])

    def test_the_import_layer_is_byte_identical(self):
        def imports(forest):
            return [e.to_dict() for e in forest.edges if e.relation == "imports"]
        self.assertEqual(imports(self.on), imports(self.off))

    def test_the_hyperedges_are_byte_identical(self):
        self.assertEqual(
            [edge.to_dict() for edge in self.on.hyperedges],
            [edge.to_dict() for edge in self.off.hyperedges],
        )

    def test_no_type_node_is_an_import_endpoint_or_a_clone_member(self):
        """``module_ids`` gates four layers at once.  If it ever grew, this is
        the assertion that says which fact got fabricated."""
        for edge in self.on.edges:
            if edge.relation != "imports":
                continue
            with self.subTest(edge=(edge.source, edge.target)):
                self.assertNotIn(edge.source, self.type_ids)
                self.assertNotIn(edge.target, self.type_ids)
        for hyperedge in self.on.hyperedges:
            with self.subTest(hyperedge=hyperedge.id):
                self.assertEqual(
                    sorted(set(hyperedge.members) & self.type_ids), [])

    def test_the_provenance_block_is_unchanged_apart_from_the_scope_key(self):
        """``scope_key`` MUST differ -- a type-bearing index is a different
        index -- and nothing else in the provenance may."""
        on_prov = dict(self.on.provenance)
        off_prov = dict(self.off.provenance)
        self.assertNotEqual(on_prov.pop("scope_key"), off_prov.pop("scope_key"))
        self.assertEqual(on_prov, off_prov)

    def test_an_index_without_the_layer_produces_the_forest_it_always_did(self):
        """Absent key -> empty loop.  The off-forest must not have acquired an
        empty relation layer, an attribute, or a different hash."""
        self.assertEqual(
            self.off.content_sha256,
            build_knowledge_forest(self.index_off).content_sha256,
        )
        self.assertEqual(self.off.layer_counts, {"imports": LAYER_COUNTS["imports"]})


# --------------------------------------------------------------------------- #
# 3. INVARIANT I3 — A TYPE NODE IS EVIDENCE, NEVER A PACKABLE ITEM             #
# --------------------------------------------------------------------------- #
class TheHierarchyIgnoresTypeNodes(_OnAndOff):

    def test_the_hierarchy_is_byte_identical(self):
        self.assertEqual(
            build_forest_hierarchy(self.on).content_sha256,
            build_forest_hierarchy(self.off).content_sha256,
        )

    def test_no_hierarchy_node_came_from_a_type_node(self):
        hierarchy = build_forest_hierarchy(self.on)
        for node in hierarchy.nodes:
            with self.subTest(node_id=node.id):
                self.assertNotIn("#", node.id)
                self.assertNotIn(node.forest_node_id, self.type_ids)

    def test_a_type_node_is_not_a_hierarchy_leaf(self):
        leaves = build_forest_hierarchy(self.on).file_node_map()
        self.assertEqual(sorted(set(leaves) & self.type_ids), [])

    def test_restricting_a_score_onto_a_type_node_fails_closed(self):
        hierarchy = build_forest_hierarchy(self.on)
        node_id = sorted(self.type_ids)[0]
        with self.assertRaisesRegex(KeyError, "unknown Forest file ID"):
            restrict_scores(hierarchy, {node_id: 1.0})

    def test_a_type_node_cannot_be_a_seed(self):
        node_id = sorted(self.type_ids)[0]
        with self.assertRaisesRegex(KeyError, "unknown Forest file ID"):
            semantic_super_sample(self.on, {node_id: 1.0}, token_budget=100)


class ATypeNodeCannotBePacked(_OnAndOff):
    """``build_context_plan`` validated MEMBERSHIP without KIND, and adding
    nodes to the forest is exactly what makes them nameable there."""

    def test_naming_a_type_node_as_a_candidate_is_refused(self):
        node_id = sorted(self.type_ids)[0]
        with self.assertRaisesRegex(KeyError, "not a packable node kind"):
            build_context_plan(self.on, {node_id: 1.0}, token_budget=10_000)

    def test_a_typo_still_reports_a_typo(self):
        """The two failures stay distinguishable: an unknown id is a typo, a
        known id of the wrong kind is a category error, and collapsing them
        would send the author of either one looking for the other's bug."""
        with self.assertRaisesRegex(KeyError, "unknown Forest node ID"):
            build_context_plan(self.on, {"nope.py": 1.0}, token_budget=10_000)

    def test_a_file_node_still_packs(self):
        node_id = sorted(self.file_ids)[0]
        plan = build_context_plan(self.on, {node_id: 1.0}, token_budget=10_000)
        self.assertEqual([item.node_id for item in plan.selected], [node_id])

    def test_the_phantom_cost_this_guard_prevents_is_real(self):
        """The number, in the record.  ``_estimated_tokens`` cannot fail: it
        falls through to ``max(1, loc) * 8``, and a type node has no ``loc``, no
        ``n_tokens`` and no bytes on disk.  So without the kind guard the packer
        does not report a gap -- it spends 8 tokens of a real budget on
        something no reader can read, and may omit the file that actually holds
        the declaration to afford it."""
        node_id = sorted(self.type_ids)[0]
        self.assertEqual(dss_mod._estimated_tokens(self.on, node_id, {}), 8)

    def test_type_and_field_are_not_file_node_kinds(self):
        self.assertEqual(FILE_NODE_KINDS, frozenset({
            "source_file", "file", "document",
        }))
        self.assertNotIn(typegraph_mod.TYPE_NODE_KIND, FILE_NODE_KINDS)
        self.assertNotIn(typegraph_mod.FIELD_NODE_KIND, FILE_NODE_KINDS)

    def test_the_whole_pipeline_produces_a_file_only_plan(self):
        """The end-to-end statement, with the config default that used to be the
        only thing holding I3 up turned OFF.  ``unknown_relation_weight`` is
        0.0 by default, which is what kept an unweighted relation out of
        ``fused``; here it is 0.5, so if the type layers were diffusible their
        scores WOULD reach the packer."""
        seed = sorted(self.file_ids)[0]
        result = semantic_super_sample(
            self.on,
            {seed: 1.0},
            token_budget=10_000,
            config=DSSConfig(unknown_relation_weight=0.5, diffusion_steps=2),
        )
        packed = [
            item.node_id
            for item in result.context_plan.selected + result.context_plan.omitted
        ]
        self.assertTrue(packed)
        self.assertEqual(sorted(set(packed) & self.type_ids), [])
        self.assertEqual(
            sorted(node_id for node_id, _ in result.final_scores
                   if node_id in self.type_ids), [])


# --------------------------------------------------------------------------- #
# 4. INVARIANT I6 — A LENS, NOT A DIFFUSION CHANNEL                            #
# --------------------------------------------------------------------------- #
class TheLensIsNotAChannel(_OnAndOff):

    def test_no_type_relation_becomes_a_channel(self):
        channels = diffuse_relation_scores(
            self.on, {sorted(self.file_ids)[0]: 1.0}, steps=2, decay=0.5)
        self.assertEqual(sorted(c.relation for c in channels), ["imports"])

    def test_the_channels_are_identical_with_the_layer_on_and_off(self):
        seed = {sorted(self.file_ids)[0]: 1.0}
        on = [c.to_dict() for c in
              diffuse_relation_scores(self.on, seed, steps=2, decay=0.5)]
        off = [c.to_dict() for c in
               diffuse_relation_scores(self.off, seed, steps=2, decay=0.5)]
        self.assertEqual(on, off)

    def test_no_type_relation_has_a_default_weight(self):
        weighted = {relation for relation, _ in DEFAULT_RELATION_WEIGHTS}
        self.assertEqual(weighted & set(typegraph_mod.RELATIONS), set())

    def test_two_files_sharing_a_type_are_not_two_hops_apart(self):
        """The measured failure, in miniature.  ``a.py`` and ``b.py`` do not
        import each other; they only both mention ``Shared``.  Uncapped, that
        alone made 53.6% of this repository's function pairs adjacent -- so if
        ``b.py`` picks up any score from a seed on ``a.py``, the graph is on its
        way to being complete and the ranking stops ranking."""
        forest = build_knowledge_forest(_hub_index())
        channels = diffuse_relation_scores(
            forest, {"a.py": 1.0}, steps=2, decay=1.0)
        for channel in channels:
            with self.subTest(relation=channel.relation):
                self.assertNotIn("b.py", dict(channel.scores))
        self.assertEqual([c.relation for c in channels], [])

    def test_a_hyperedge_cannot_smuggle_a_type_node_into_diffusion(self):
        """The hyperedge half of the same filter: member-to-group-to-member
        message passing would otherwise make every member of a clone group a
        one-hop neighbour of a type node listed alongside it."""
        index = _hub_index()
        index["duplication"] = {
            "unit_clusters": [{
                "name": "same", "count": 2,
                "sites": [{"module": "a.py"}, {"module": "b.py"}],
            }],
            "renamed_clusters": [], "near_clusters": [], "window_clusters": [],
        }
        forest = build_knowledge_forest(index)
        forced = forest.__class__(
            root=forest.root,
            nodes=forest.nodes,
            edges=forest.edges,
            hyperedges=tuple(
                edge.__class__(
                    id=edge.id, relation=edge.relation,
                    members=edge.members + ("type:a.py#Shared",),
                    weight=edge.weight, evidence=edge.evidence,
                    attributes=edge.attributes,
                )
                for edge in forest.hyperedges
            ),
            provenance=forest.provenance,
        )
        channels = diffuse_relation_scores(
            forced, {"a.py": 1.0}, steps=1, decay=1.0)
        scores = {c.relation: dict(c.scores) for c in channels}
        self.assertEqual(scores["clone_exact"], {"b.py": 1.0})


# --------------------------------------------------------------------------- #
# 5. DETERMINISM                                                               #
# --------------------------------------------------------------------------- #
class TheBuildIsDeterministic(_OnAndOff):

    def test_two_builds_of_one_index_are_byte_identical(self):
        first = build_knowledge_forest(self.index_on)
        second = build_knowledge_forest(self.index_on)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(len(first.content_sha256), 64)
        self.assertEqual(first.content_sha256, self.on.content_sha256)

    def test_the_hash_moves_when_the_layer_is_turned_on(self):
        """Not a nuisance: it is why the layer is opt-in.  A type-bearing index
        yields a different forest, so every consumer that hashes or counts one
        moves, and that has to be a deliberate re-baselining rather than a
        side effect of an unrelated flag."""
        self.assertNotEqual(self.on.content_sha256, self.off.content_sha256)

    def test_the_order_of_the_index_rows_does_not_reach_the_output(self):
        """The strong form of determinism: the forest is sorted by ITS OWN
        rules, not by the order it happened to receive.  Two processes producing
        blocks in different orders must still agree byte for byte."""
        shuffled = copy.deepcopy(self.index_on)
        rng = random.Random(20260730)
        rng.shuffle(shuffled["type_nodes"])
        for relation in list(shuffled["type_edges"]):
            rng.shuffle(shuffled["type_edges"][relation])
        self.assertNotEqual(
            json.dumps(shuffled["type_nodes"], sort_keys=True),
            json.dumps(self.index_on["type_nodes"], sort_keys=True),
        )
        self.assertEqual(
            build_knowledge_forest(shuffled).content_sha256,
            self.on.content_sha256,
        )

    def test_a_second_process_agrees_byte_for_byte(self):
        """Determinism is load-bearing and in-process repetition does not prove
        it: set iteration order is stable WITHIN a process and salted BETWEEN
        them.  ``module_ids``/``type_ids`` are sets, and the day one of them
        reaches output instead of only gating membership, this is the assertion
        that notices.  The index is handed over as JSON rather than rebuilt, so
        the subprocess measures the forest and not the scan (and the round trip
        also pins that a tuple and a list of the same rows hash alike)."""
        payload = json.dumps(self.index_on)
        self.assertEqual(
            build_knowledge_forest(json.loads(payload)).content_sha256,
            self.on.content_sha256,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            path.write_text(payload, encoding="utf-8")
            script = (
                "import json,sys;"
                "from daedalus.structcore.forest import build_knowledge_forest;"
                "print(build_knowledge_forest("
                "json.loads(open(sys.argv[1],encoding='utf-8').read())"
                ").content_sha256)"
            )
            seen = set()
            for salt in ("0", "1", "12345"):
                env = dict(os.environ, PYTHONHASHSEED=salt)
                out = subprocess.run(
                    [sys.executable, "-c", script, str(path)],
                    cwd=str(REPO_ROOT), env=env, capture_output=True,
                    text=True, check=True,
                )
                seen.add(out.stdout.strip())
            self.assertEqual(seen, {self.on.content_sha256})

    def test_the_node_and_edge_order_is_total(self):
        """A stable sort with ties left to insertion order is deterministic only
        by accident.  Both sequences must be strictly increasing under a key
        that includes the attributes."""
        def node_key(node: ForestNode):
            return (0 if node.kind in FILE_NODE_KINDS else 1, node.id)

        keys = [node_key(node) for node in self.on.nodes]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))

        edge_keys = [
            (edge.relation, edge.source, edge.target,
             json.dumps(edge.to_dict()["attributes"], sort_keys=True))
            for edge in self.on.edges
        ]
        self.assertEqual(edge_keys, sorted(edge_keys))
        self.assertEqual(len(set(edge_keys)), len(edge_keys))


# --------------------------------------------------------------------------- #
# 6. THE GATES, ASKED WITH A HAND-WRITTEN INDEX                                #
# --------------------------------------------------------------------------- #
def _hub_index() -> dict:
    """Two files that share a type and import nothing.  No filesystem: this is
    the shape of the hazard, written down."""
    return {
        "root": "/repo",
        "modules": {
            "a.py": {"language": "python", "loc": 5},
            "b.py": {"language": "python", "loc": 5},
        },
        "import_edges": {},
        "type_nodes": [
            {"id": "type:a.py#Shared", "kind": "type", "module": "a.py",
             "qualname": "Shared", "name": "Shared", "line": 1, "end_line": 2},
        ],
        "type_edges": {
            "consumes": [
                {"source": "a.py", "target": "type:a.py#Shared",
                 "attributes": {"function_ref": "a.py#f", "param": "x"}},
                {"source": "b.py", "target": "type:a.py#Shared",
                 "attributes": {"function_ref": "b.py#g", "param": "y"}},
            ],
        },
    }


class TheGatesRefuseRatherThanRepair(unittest.TestCase):
    """Every refusal below drops a row instead of renaming, merging or inventing
    one.  A forest that disagrees with the index it was normalised from is worse
    than a forest that is missing evidence: the second is legible."""

    def _forest(self, mutate=None):
        index = _hub_index()
        if mutate is not None:
            mutate(index)
        return build_knowledge_forest(index)

    def _ids(self, forest):
        return {node.id for node in forest.nodes}

    def test_the_baseline_carries_both_edges(self):
        forest = self._forest()
        self.assertEqual(forest.layer_counts, {"consumes": 2})
        self.assertIn("type:a.py#Shared", self._ids(forest))

    def test_a_row_whose_id_collides_with_a_module_is_refused(self):
        """``build_forest_hierarchy`` raises when two ids map to one path, so a
        colliding id is not a cosmetic problem -- it takes the hierarchy down."""
        def mutate(index):
            index["type_nodes"][0]["id"] = "a.py"
            for row in index["type_edges"]["consumes"]:
                row["target"] = "a.py"
        forest = self._forest(mutate)
        self.assertEqual(
            [node.kind for node in forest.nodes], ["source_file", "source_file"])
        self.assertEqual(forest.layer_counts, {})
        build_forest_hierarchy(forest)

    def test_a_row_outside_the_namespace_is_refused(self):
        def mutate(index):
            index["type_nodes"][0]["id"] = "pkg/mod.py"
            for row in index["type_edges"]["consumes"]:
                row["target"] = "pkg/mod.py"
        forest = self._forest(mutate)
        self.assertNotIn("pkg/mod.py", self._ids(forest))
        self.assertEqual(forest.layer_counts, {})

    def test_a_prefix_without_the_separator_is_refused(self):
        """``type:pkg/mod.py`` has the prefix and no ``#``, so
        ``build_forest_hierarchy`` would read it as the directory ``type:pkg``.
        Both halves of the scheme are load-bearing."""
        def mutate(index):
            index["type_nodes"][0]["id"] = "type:pkg/mod.py"
            for row in index["type_edges"]["consumes"]:
                row["target"] = "type:pkg/mod.py"
        forest = self._forest(mutate)
        self.assertNotIn("type:pkg/mod.py", self._ids(forest))

    def test_a_row_claiming_a_file_kind_is_refused(self):
        """``type_nodes`` is not a second way to declare a file."""
        def mutate(index):
            index["type_nodes"][0]["kind"] = "source_file"
        forest = self._forest(mutate)
        self.assertNotIn("type:a.py#Shared", self._ids(forest))
        self.assertEqual(forest.layer_counts, {})

    def test_an_edge_to_an_unpublished_target_is_dropped(self):
        def mutate(index):
            index["type_edges"]["consumes"].append({
                "source": "a.py", "target": "type:a.py#Ghost",
                "attributes": {"function_ref": "a.py#f"},
            })
        forest = self._forest(mutate)
        self.assertEqual(forest.layer_counts, {"consumes": 2})

    def test_an_edge_from_an_unknown_source_is_dropped(self):
        def mutate(index):
            index["type_edges"]["consumes"].append({
                "source": "vendor/x.py", "target": "type:a.py#Shared",
                "attributes": {"function_ref": "vendor/x.py#f"},
            })
        forest = self._forest(mutate)
        self.assertEqual(forest.layer_counts, {"consumes": 2})

    def test_a_reserved_relation_name_is_refused_rather_than_merged(self):
        """An edge with a type endpoint filed under ``imports`` would be read as
        an import by every consumer of that layer, starting with the
        reachability the safety fence is built on."""
        def mutate(index):
            index["type_edges"]["imports"] = [{
                "source": "a.py", "target": "type:a.py#Shared", "attributes": {},
            }]
        forest = self._forest(mutate)
        self.assertEqual(forest.layer_counts, {"consumes": 2})
        self.assertEqual([e for e in forest.edges if e.relation == "imports"], [])

    def test_a_new_relation_name_needs_no_edit_here(self):
        """``instantiates`` is the planned seventh relation.  The gates are
        kind-based, so a name list is not a thing that can be forgotten."""
        def mutate(index):
            index["type_edges"]["instantiates"] = [{
                "source": "a.py", "target": "type:a.py#Shared",
                "attributes": {"function_ref": "a.py#f"},
            }]
        forest = self._forest(mutate)
        self.assertEqual(
            forest.layer_counts, {"consumes": 2, "instantiates": 1})

    def test_two_identical_rows_are_one_fact(self):
        def mutate(index):
            index["type_edges"]["consumes"].append(
                dict(index["type_edges"]["consumes"][0]))
        forest = self._forest(mutate)
        self.assertEqual(forest.layer_counts, {"consumes": 2})

    def test_two_rows_differing_only_in_attributes_are_two_facts(self):
        """One function can consume the same type through two parameters, and
        collapsing those would delete the ``param`` evidence that makes the edge
        worth publishing at all."""
        def mutate(index):
            row = dict(index["type_edges"]["consumes"][0])
            row["attributes"] = {**row["attributes"], "param": "second"}
            index["type_edges"]["consumes"].append(row)
        forest = self._forest(mutate)
        self.assertEqual(forest.layer_counts, {"consumes": 3})

    def test_module_ids_did_not_grow_for_the_import_layer(self):
        """``module_ids`` is not a convenience variable, it is the membership
        gate of four layers, and the type node loop runs BEFORE all four.  If a
        type id ever joined that set, this index -- whose import edge names a
        type node -- would publish an import from a file to a data structure,
        and ``fan_in`` and every reachability answer downstream would move."""
        def mutate(index):
            index["import_edges"]["a.py"] = ["type:a.py#Shared"]
        forest = self._forest(mutate)
        self.assertEqual([e for e in forest.edges if e.relation == "imports"], [])

    def test_module_ids_did_not_grow_for_the_document_layer(self):
        def mutate(index):
            index["document_links"] = {"a.py": ["type:a.py#Shared"]}
        forest = self._forest(mutate)
        self.assertEqual(
            [e for e in forest.edges if e.relation == "documents"], [])

    def test_module_ids_did_not_grow_for_the_co_change_layer(self):
        index = _hub_index()
        forest = build_knowledge_forest(index, temporal_pairs=[
            {"a": "a.py", "b": "type:a.py#Shared", "lift": 2.0},
        ])
        self.assertEqual(
            [e for e in forest.edges if e.relation == "co_change"], [])

    def test_module_ids_did_not_grow_for_the_clone_hyperedges(self):
        """The one that would be published in the PRECISE tier: a type node
        accepted as a clone-group member is a claim that a data structure is a
        duplicate of a file."""
        def mutate(index):
            index["duplication"] = {
                "unit_clusters": [{
                    "name": "same", "count": 2,
                    "sites": [{"module": "a.py"},
                              {"module": "type:a.py#Shared"}],
                }],
                "renamed_clusters": [], "near_clusters": [],
                "window_clusters": [{
                    "files": ["b.py", "type:a.py#Shared"], "shared_runs": 3,
                }],
            }
        forest = self._forest(mutate)
        self.assertEqual(forest.hyperedges, ())

    def test_a_malformed_row_is_skipped_not_crashed(self):
        def mutate(index):
            index["type_nodes"].append("not-a-mapping")
            index["type_edges"]["consumes"].append(["not", "a", "mapping"])
        forest = self._forest(mutate)
        self.assertEqual(forest.layer_counts, {"consumes": 2})


if __name__ == "__main__":
    unittest.main()
