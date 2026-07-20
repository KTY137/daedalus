"""Regression — the code-map `graph` payload (index.py + report.py).

``build_index`` now additionally returns ``import_edges`` (unified rel->rel
import edges for ALL languages) and ``module_heat`` (the full churn x
complexity ranking; ``hotspots`` is just ``module_heat[:15]``). New public
helper ``score_modules(modules, churn)`` returns the full ranking.

``structure_summary`` (report.py) now returns a ``graph`` key: nodes carry
heat, edges are the import graph, and truncation (by node/edge count) is
reported honestly rather than silently dropping data.

Pins the invariants that matter:
  1. no dangling edges — every edge's source/target is a node, even truncated.
  2. one consistent node namespace — rel paths for EVERY language, including
     Python (whose pre-existing ``fan_in`` keys by dotted module name instead,
     which is exactly why the graph recomputes its own fan-in from
     ``import_edges`` rather than reusing ``fan_in``/``dependencies``).
  3. truncation is honest — ``truncated`` flips True and the *_total counts
     stay accurate, while invariant 1 still holds.
  4. ``hotspots == module_heat[:15]``; ``score_modules`` ranks every module.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.index import score_modules
from daedalus.structcore.report import structure_summary


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _py_module(*, imports: str | None, pad_lines: int) -> str:
    """A tiny python module, sized (via ``pad_lines``) to control its
    churn x complexity score deterministically (score ~= loc / 50 here, since
    there are no guards/long-functions and no git churn in a fresh tempdir)."""
    lines = []
    if imports:
        lines.append(f"from pkg import {imports}")
    lines.append("")
    lines.append("def f():")
    lines.append("    return 1")
    lines.extend(["x = 1"] * pad_lines)
    return "\n".join(lines) + "\n"


class GraphInvariantsTest(unittest.TestCase):
    """Chain a -> b -> c -> d (a imports b, b imports c, c imports d), sized
    so score(d) > score(c) > score(b) > score(a) > score(__init__) — a
    deterministic heat order to truncate against."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", _py_module(imports="b", pad_lines=1))
        _write(self.root, "pkg/b.py", _py_module(imports="c", pad_lines=300))
        _write(self.root, "pkg/c.py", _py_module(imports="d", pad_lines=600))
        _write(self.root, "pkg/d.py", _py_module(imports=None, pad_lines=900))
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _heat_order(self):
        return [h["module"] for h in self.idx["module_heat"]]

    def test_fixture_heat_order_is_deterministic(self):
        # Sanity check the fixture itself before trusting truncation on it.
        order = self._heat_order()
        self.assertEqual(order[:4], ["pkg/d.py", "pkg/c.py", "pkg/b.py", "pkg/a.py"])

    def test_import_edges_are_rel_to_rel_for_python(self):
        edges = self.idx["import_edges"]
        self.assertEqual(edges.get("pkg/a.py"), ["pkg/b.py"])
        self.assertEqual(edges.get("pkg/b.py"), ["pkg/c.py"])
        self.assertEqual(edges.get("pkg/c.py"), ["pkg/d.py"])

    def test_node_ids_are_rel_paths_not_dotted_python_modules(self):
        # fan_in (pre-existing) keys Python by DOTTED module name -- that's
        # exactly the mismatch the graph's own node namespace must NOT repeat.
        self.assertIn("pkg.b", self.idx["fan_in"])  # the old, dotted namespace
        summary = structure_summary(self.idx)
        node_ids = {n["module"] for n in summary["graph"]["nodes"]}
        self.assertIn("pkg/a.py", node_ids)
        self.assertIn("pkg/d.py", node_ids)
        for node_id in node_ids:
            self.assertTrue("/" in node_id or node_id.endswith(".py"),
                            f"node id {node_id!r} looks dotted, not a rel path")
        self.assertNotIn("pkg.a", node_ids)
        self.assertNotIn("pkg.b", node_ids)

    def test_untruncated_graph_has_all_nodes_and_edges_no_dangling(self):
        summary = structure_summary(self.idx)
        g = summary["graph"]
        self.assertFalse(g["truncated"])
        self.assertEqual(g["n_nodes_total"], 5)   # __init__, a, b, c, d
        self.assertEqual(g["n_edges_total"], 3)   # a->b, b->c, c->d
        self.assertEqual(len(g["nodes"]), 5)
        self.assertEqual(len(g["edges"]), 3)
        node_ids = {n["module"] for n in g["nodes"]}
        for e in g["edges"]:
            self.assertIn(e["source"], node_ids)
            self.assertIn(e["target"], node_ids)

    def test_node_truncation_drops_edges_touching_dropped_nodes_honestly(self):
        # Keep only the top-2 heat nodes: d (score ~18.1) and c (~12.1).
        # b (~6.1) and a (~0.1) and __init__ (0) are dropped.
        summary = structure_summary(self.idx, max_graph_nodes=2, max_graph_edges=8000)
        g = summary["graph"]
        node_ids = {n["module"] for n in g["nodes"]}
        self.assertEqual(node_ids, {"pkg/c.py", "pkg/d.py"})

        self.assertTrue(g["truncated"])
        self.assertEqual(g["n_nodes_total"], 5)  # true total, despite truncation
        self.assertEqual(g["n_edges_total"], 3)  # true total, despite truncation

        # Invariant 1 (no dangling edges) MUST still hold under truncation:
        # a->b and b->c both touch a dropped node and must be gone; only the
        # c->d edge (both endpoints kept) may survive.
        self.assertEqual(len(g["edges"]), 1)
        for e in g["edges"]:
            self.assertIn(e["source"], node_ids)
            self.assertIn(e["target"], node_ids)
        self.assertEqual(g["edges"], [{"source": "pkg/c.py", "target": "pkg/d.py"}])

    def test_truncated_reflects_ELIGIBLE_edges_not_the_whole_index(self):
        """``truncated`` must mean "edges that belong on this map were
        withheld" -- not "the index contains edges this map never wanted".

        Deriving it from ``n_edges_total`` made it structurally always True on
        any repo with off-map traffic (project_tct: 42 shown of 8558, of which
        8516 had NEITHER endpoint on the map), so the flag carried no signal.
        Here node truncation makes 2 of 3 edges off-map; the one eligible edge
        IS shown, so nothing was withheld and the flag must stay False even
        though shown (1) is far below n_edges_total (3).
        """
        g = structure_summary(self.idx, max_graph_nodes=2,
                              max_graph_edges=8000)["graph"]
        self.assertEqual(g["n_edges_total"], 3)      # whole index
        self.assertEqual(g["n_edges_eligible"], 1)   # both ends displayed
        self.assertEqual(g["n_edges_shown"], 1)
        self.assertEqual(g["n_edges_offmap"], 2)     # stated, not implied
        # Nodes WERE truncated (2 of 5), so the flag is True for that reason --
        # but it must not be True on the edge axis.
        self.assertEqual(len(g["edges"]), g["n_edges_eligible"])

    def test_no_truncation_when_every_eligible_edge_is_shown(self):
        """The full map: eligible == shown == total, flag False."""
        g = structure_summary(self.idx)["graph"]
        self.assertEqual(g["n_edges_eligible"], 3)
        self.assertEqual(g["n_edges_shown"], 3)
        self.assertEqual(g["n_edges_offmap"], 0)
        self.assertFalse(g["truncated"])

    def test_edge_cap_below_eligible_is_reported_as_truncated(self):
        """The one case ``truncated`` is actually for: eligible edges withheld
        by the display cap."""
        g = structure_summary(self.idx, max_graph_nodes=2000,
                              max_graph_edges=1)["graph"]
        self.assertEqual(g["n_edges_eligible"], 3)
        self.assertEqual(g["n_edges_shown"], 1)
        self.assertTrue(g["truncated"])

    def test_edge_truncation_is_reported_and_stays_non_dangling(self):
        # All 5 nodes kept, but only 1 of 3 edges survives the edge cap.
        summary = structure_summary(self.idx, max_graph_nodes=2000, max_graph_edges=1)
        g = summary["graph"]
        node_ids = {n["module"] for n in g["nodes"]}
        self.assertEqual(len(node_ids), 5)
        self.assertTrue(g["truncated"])
        self.assertEqual(g["n_edges_total"], 3)
        self.assertEqual(len(g["edges"]), 1)
        for e in g["edges"]:
            self.assertIn(e["source"], node_ids)
            self.assertIn(e["target"], node_ids)


class ScoreModulesAndHotspotsTest(unittest.TestCase):
    """20 modules -> module_heat must rank all 20; hotspots is just the top 15
    of that SAME ranking (not an independently-scored/truncated list)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for i in range(20):
            _write(self.root, f"pkg/m{i}.py",
                  f"def f{i}():\n    return {i}\n" + "x = 1\n" * i)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_hotspots_is_top15_of_module_heat(self):
        self.assertEqual(len(self.idx["module_heat"]), 20)
        self.assertEqual(len(self.idx["hotspots"]), 15)
        self.assertEqual(self.idx["hotspots"], self.idx["module_heat"][:15])

    def test_score_modules_ranks_every_module(self):
        scored = score_modules(self.idx["modules"])
        self.assertEqual(len(scored), len(self.idx["modules"]))
        self.assertEqual(len(scored), 20)
        self.assertEqual({s["module"] for s in scored}, set(self.idx["modules"].keys()))
        # Sorted descending by score (ties broken arbitrarily but monotonic).
        scores = [s["score"] for s in scored]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
