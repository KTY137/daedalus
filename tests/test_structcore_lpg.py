"""The LPG projection: the explicit mapping from the Forest's multiplex
contract onto the labeled-property-graph model.

Regression-locks the three honesty decisions the projection is built on:
hyperedges are reified rather than expanded into fake cliques, an undirected
edge is one relationship rather than a mirrored double-counting pair, and the
projection is deterministic and bound to its source forest by content hash.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from daedalus.structcore.lpg import SCHEMA_VERSION, lpg_sha256, to_lpg, write_lpg


def _forest(node_order=None, edge_order=None) -> KnowledgeForest:
    nodes = [
        ForestNode("pkg/a.py", "source_file", {"loc": 10}),
        ForestNode("pkg/b.py", "source_file", {"loc": 20}),
        ForestNode("README.md", "document", {"n_sections": 3}),
        ForestNode("type:pkg/a.py#Foo", "type", {"name": "Foo"}),
    ]
    edges = [
        ForestEdge("pkg/a.py", "pkg/b.py", "imports", True,
                   evidence=("structcore.import_edges",)),
        ForestEdge("README.md", "pkg/a.py", "documents", True),
        ForestEdge("pkg/a.py", "pkg/b.py", "co_change", False,
                   weight=1.4, attributes={"lift": 1.4}),
        ForestEdge("pkg/a.py", "type:pkg/a.py#Foo", "has_field", True,
                   attributes={"field": "x"}),
    ]
    hyperedges = [
        ForestHyperedge("clone_exact:abc", "clone_exact",
                        ("pkg/a.py", "pkg/b.py")),
    ]
    if node_order:
        nodes = [nodes[i] for i in node_order]
    if edge_order:
        edges = [edges[i] for i in edge_order]
    return KnowledgeForest(
        "repo", tuple(nodes), tuple(edges), tuple(hyperedges),
        {"built_by": "test"},
    )


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class Determinism(unittest.TestCase):
    def test_pure_function_byte_identical(self):
        forest = _forest()
        self.assertEqual(_canonical(to_lpg(forest)), _canonical(to_lpg(forest)))

    def test_payload_is_input_order_independent(self):
        # Tuple order changes the forest's own content hash (a forest IS its
        # bytes), so the BINDING may differ -- but the projected nodes and
        # relationships must come out identical regardless of input order.
        a = to_lpg(_forest())
        b = to_lpg(_forest(node_order=[3, 2, 1, 0], edge_order=[2, 0, 3, 1]))
        self.assertEqual(_canonical(a["nodes"]), _canonical(b["nodes"]))
        self.assertEqual(
            _canonical(a["relationships"]), _canonical(b["relationships"])
        )

    def test_binding_tracks_the_source_forest(self):
        forest = _forest()
        lpg = to_lpg(forest)
        self.assertEqual(lpg["forest_sha256"], forest.content_sha256)
        self.assertEqual(lpg["schema"], SCHEMA_VERSION)


class HyperedgeReification(unittest.TestCase):
    def test_no_pairwise_clone_edges_are_manufactured(self):
        lpg = to_lpg(_forest())
        self.assertEqual(
            [r for r in lpg["relationships"] if r["type"] == "clone_exact"], []
        )

    def test_group_is_a_marked_node_with_memberships(self):
        lpg = to_lpg(_forest())
        hyper = [n for n in lpg["nodes"] if "hyperedge" in n["labels"]]
        self.assertEqual(len(hyper), 1)
        self.assertEqual(hyper[0]["labels"], ["hyperedge", "clone_exact"])
        self.assertTrue(hyper[0]["properties"]["reified"])
        self.assertEqual(hyper[0]["properties"]["n_members"], 2)
        members = [
            r for r in lpg["relationships"] if r["type"] == "hyperedge_member"
        ]
        self.assertEqual(len(members), 2)
        for rel in members:
            self.assertEqual(rel["start"], hyper[0]["id"])
            self.assertEqual(rel["properties"]["relation"], "clone_exact")


class EdgeSemantics(unittest.TestCase):
    def test_undirected_edge_is_one_relationship(self):
        lpg = to_lpg(_forest())
        co = [r for r in lpg["relationships"] if r["type"] == "co_change"]
        self.assertEqual(len(co), 1)
        self.assertIs(co[0]["properties"]["directed"], False)
        imports = [r for r in lpg["relationships"] if r["type"] == "imports"]
        self.assertIs(imports[0]["properties"]["directed"], True)

    def test_same_endpoints_different_attributes_keep_distinct_ids(self):
        # forest.py dedups type edges on the FULL row for this exact reason;
        # the projection must not collapse them either.
        forest = KnowledgeForest(
            "repo",
            (ForestNode("a.py", "source_file", {}),
             ForestNode("type:a.py#T", "type", {})),
            (ForestEdge("a.py", "type:a.py#T", "consumes", True,
                        attributes={"param": "x"}),
             ForestEdge("a.py", "type:a.py#T", "consumes", True,
                        attributes={"param": "y"})),
            (),
            {},
        )
        rels = to_lpg(forest)["relationships"]
        self.assertEqual(len(rels), 2)
        self.assertNotEqual(rels[0]["id"], rels[1]["id"])


class PlaneProperty(unittest.TestCase):
    def test_known_kinds_get_their_plane(self):
        lpg = to_lpg(_forest())
        by_id = {n["id"]: n for n in lpg["nodes"]}
        self.assertEqual(by_id["pkg/a.py"]["properties"]["plane"], "code")
        self.assertEqual(by_id["README.md"]["properties"]["plane"], "knowledge")
        self.assertEqual(
            by_id["type:pkg/a.py#Foo"]["properties"]["plane"], "type"
        )

    def test_unknown_kind_gets_no_plane_key(self):
        # Under-report rather than guess: a kind this projection does not know
        # must not be assigned a plane by accident.
        forest = KnowledgeForest(
            "repo", (ForestNode("w", "widget", {}),), (), (), {}
        )
        node = to_lpg(forest)["nodes"][0]
        self.assertNotIn("plane", node["properties"])
        self.assertEqual(node["labels"], ["widget"])


class WrittenBytes(unittest.TestCase):
    def test_file_bytes_match_the_digest(self):
        forest = _forest()
        lpg = to_lpg(forest)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.lpg.json"
            digest = write_lpg(lpg, out)
            body = out.read_text(encoding="utf-8")
        self.assertEqual(digest, lpg_sha256(lpg))
        self.assertEqual(json.loads(body), json.loads(_canonical(to_lpg(forest))))


class CliWire(unittest.TestCase):
    def test_lpg_flag_writes_a_bound_projection(self):
        from daedalus.structcore.__main__ import main

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
            (repo / "a.py").write_text("import b\n", encoding="utf-8")
            out = Path(tmp) / "proj.json"
            rc = main([str(repo), "--lpg", str(out)])
            self.assertEqual(rc, 0)
            lpg = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(lpg["schema"], SCHEMA_VERSION)
        self.assertTrue(lpg["forest_sha256"])
        ids = {n["id"] for n in lpg["nodes"]}
        self.assertIn("a.py", ids)
        self.assertIn("b.py", ids)


if __name__ == "__main__":
    unittest.main()
