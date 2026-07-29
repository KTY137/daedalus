"""Ground-truth tests for daedalus.mapping.spectral.

THE ANTI-NUMEROLOGY RULE. Every metric in spectral.py is tested against a
synthetic graph whose answer is known BEFORE the code runs -- a barbell whose
bridge we placed ourselves, planted communities we chose the membership of. A
spectral number that is only ever checked against the repo it was written for is
astrology: it always "looks about right" because there is nothing it could
contradict. These graphs can contradict it.

Style: unittest.TestCase (tests/test_hardening.py convention; the repo runs both
that and bare-pytest files under pytest).
"""

from __future__ import annotations

import unittest

from daedalus.mapping import spectral


def _clique(prefix: str, n: int) -> dict[str, list[str]]:
    nodes = [f"{prefix}/m{i}.py" for i in range(n)]
    return {a: [b for b in nodes if b != a] for a in nodes}


def _barbell(n: int = 10) -> "object":
    """Two n-cliques joined by exactly ONE bridge edge. Ground truth: the only
    honest 2-way cut severs the bridge, and there are exactly 2 clusters."""
    edges = {**_clique("left", n), **_clique("right", n)}
    edges.setdefault("left/m0.py", []).append("right/m0.py")
    return spectral.graph_from_edges(edges)


@unittest.skipUnless(spectral.HAVE_MATH, "math extra not installed")
class FiedlerGroundTruth(unittest.TestCase):
    """1. Fiedler / algebraic connectivity: find the bridge we planted."""

    def test_fiedler_cut_severs_the_single_bridge_edge(self):
        graph = _barbell()
        report = spectral.fiedler_report(graph)
        self.assertTrue(report["available"])
        # GROUND TRUTH: the cut is the one bridge edge, nothing else.
        self.assertEqual(report["cut_edges"], 1)
        self.assertEqual(sorted(report["side_sizes"]), [10, 10])
        values = report["fiedler_values"]
        left = {v >= 0 for k, v in values.items() if k.startswith("left/")}
        right = {v >= 0 for k, v in values.items() if k.startswith("right/")}
        self.assertEqual(len(left), 1, "a 10-clique must not be split")
        self.assertEqual(len(right), 1, "a 10-clique must not be split")
        self.assertNotEqual(left, right, "the two cliques must land on opposite sides")

    def test_declared_boundary_that_matches_the_seam_reads_as_real_seam(self):
        graph = _barbell()
        partition = spectral.declared_partition(graph.nodes)
        report = spectral.fiedler_report(graph, partition)
        for pkg in ("left", "right"):
            self.assertEqual(report["boundary_agreement"][pkg]["boundary_agreement"], 1.0)
            self.assertEqual(report["boundary_agreement"][pkg]["reads_as"], "real seam")

    def test_declared_boundary_that_crosses_the_seam_reads_as_false_wall(self):
        """A partition deliberately built to straddle the true cut must be
        called a false wall -- the metric has to be able to say WE ARE WRONG."""
        graph = _barbell()
        nodes = sorted(graph.nodes)
        straddle = {
            "mixed_a": [n for i, n in enumerate(nodes) if i % 2 == 0],
            "mixed_b": [n for i, n in enumerate(nodes) if i % 2 == 1],
        }
        report = spectral.fiedler_report(graph, straddle)
        for pkg in ("mixed_a", "mixed_b"):
            self.assertLessEqual(report["boundary_agreement"][pkg]["boundary_agreement"], 0.7)
            self.assertEqual(report["boundary_agreement"][pkg]["reads_as"], "false wall")

    def test_disconnected_graph_reports_zero_globally_and_never_fabricates(self):
        """Two cliques, NO bridge. Global algebraic connectivity is exactly 0
        and the scope value must be labelled as the component's, not the graph's."""
        graph = spectral.graph_from_edges({**_clique("left", 6), **_clique("right", 6)})
        report = spectral.fiedler_report(graph)
        self.assertTrue(report["available"])
        self.assertFalse(report["connected"])
        self.assertEqual(report["connected_components"], 2)
        self.assertEqual(report["algebraic_connectivity_global"], 0.0)
        self.assertEqual(report["scope"], "largest connected component")
        self.assertGreater(report["algebraic_connectivity_scope"], 0.0)

    def test_fiedler_values_are_deterministic_across_runs(self):
        """Provenance requires it: the eigenvector sign is arbitrary, so an
        un-pinned sign makes two runs over an unchanged tree 'disagree'."""
        graph = _barbell()
        first = spectral.fiedler_report(graph)["fiedler_values"]
        second = spectral.fiedler_report(graph)["fiedler_values"]
        self.assertEqual(first, second)


@unittest.skipUnless(spectral.HAVE_MATH, "math extra not installed")
class ModularityGroundTruth(unittest.TestCase):
    """2. Newman modularity: the planted partition must beat a random one."""

    @staticmethod
    def _planted(k: int = 3, n: int = 8):
        edges: dict[str, list[str]] = {}
        for c in range(k):
            edges.update(_clique(f"c{c}", n))
        # one thin inter-community edge each, so the graph is connected but the
        # planted structure is still overwhelming
        for c in range(k):
            edges.setdefault(f"c{c}/m0.py", []).append(f"c{(c + 1) % k}/m0.py")
        return spectral.graph_from_edges(edges)

    def test_planted_partition_beats_random_partitions(self):
        graph = self._planted()
        partition = spectral.declared_partition(graph.nodes)
        report = spectral.modularity_report(graph, partition)
        self.assertTrue(report["available"])
        self.assertEqual(report["blocks"], 3)
        # GROUND TRUTH: we built these communities, so Q must be high AND must
        # beat the best of 50 random same-size partitions -- not just the mean.
        self.assertGreater(report["declared"], 0.3)
        self.assertTrue(report["beats_random"])
        self.assertGreater(report["lift"], 0.0)
        self.assertGreater(report["declared"], report["random_max"])
        self.assertEqual(report["reads_as"], "real structure")

    def test_a_shuffled_partition_does_not_beat_random(self):
        """The metric must FAIL to endorse a meaningless partition, or it
        endorses everything and measures nothing."""
        graph = self._planted()
        nodes = sorted(graph.nodes)
        nonsense = {"a": nodes[::2], "b": nodes[1::2]}
        report = spectral.modularity_report(graph, nonsense)
        self.assertFalse(report["beats_random"])
        self.assertLess(report["declared"], 0.3)

    def test_modularity_is_deterministic_for_a_fixed_seed(self):
        graph = self._planted()
        partition = spectral.declared_partition(graph.nodes)
        a = spectral.modularity_report(graph, partition, seed=7)
        b = spectral.modularity_report(graph, partition, seed=7)
        self.assertEqual(a, b)


@unittest.skipUnless(spectral.HAVE_MATH, "math extra not installed")
class ConductanceGroundTruth(unittest.TestCase):
    """3. Conductance: rank the leaky package above the tight one."""

    def test_tight_clique_scores_low_and_pass_through_scores_high(self):
        # 'core' is a 10-clique (tight). 'shim' is 2 modules with NO internal
        # edge, each wired only to core -- ground truth conductance 1.0.
        edges = _clique("core", 10)
        edges["shim/a.py"] = ["core/m1.py"]
        edges["shim/b.py"] = ["core/m2.py"]
        graph = spectral.graph_from_edges(edges)
        partition = spectral.declared_partition(graph.nodes)
        report = spectral.conductance_report(graph, partition)
        rows = {r["package"]: r for r in report["rows"]}
        self.assertEqual(rows["shim"]["leak_rate"], 1.0)
        self.assertEqual(rows["shim"]["internal_edges"], 0)
        self.assertEqual(rows["shim"]["reads_as"], "pass-through")
        # GROUND TRUTH: core is a 10-clique with 2 outbound edges out of 92
        # endpoints -- it is TIGHT, and the metric must say so.
        self.assertLess(rows["core"]["leak_rate"], 0.2)
        self.assertEqual(rows["core"]["reads_as"], "tight")
        # worst-first ordering is the only reason to read the list
        self.assertEqual(report["rows"][0]["package"], "shim")

    def test_symmetric_conductance_cannot_tell_the_two_apart(self):
        """Why leak_rate is the ranking key and textbook conductance is not.

        cut/min(vol) is symmetric: on a two-block partition it gives the tight
        clique and the shim the SAME number. Pinned as a test so nobody
        'simplifies' the report back to the single misleading value.
        """
        edges = _clique("core", 10)
        edges["shim/a.py"] = ["core/m1.py"]
        edges["shim/b.py"] = ["core/m2.py"]
        graph = spectral.graph_from_edges(edges)
        report = spectral.conductance_report(
            graph, spectral.declared_partition(graph.nodes))
        rows = {r["package"]: r for r in report["rows"]}
        self.assertEqual(rows["core"]["conductance_symmetric"],
                         rows["shim"]["conductance_symmetric"])
        self.assertNotEqual(rows["core"]["leak_rate"], rows["shim"]["leak_rate"])

    def test_package_that_is_the_whole_graph_reports_none_not_zero(self):
        graph = spectral.graph_from_edges(_clique("only", 5))
        report = spectral.conductance_report(graph, spectral.declared_partition(graph.nodes))
        self.assertIsNone(report["rows"][0]["leak_rate"])

    def test_isolated_rest_of_graph_does_not_crash_the_symmetric_value(self):
        """nx.conductance raises ZeroDivisionError when the complement has zero
        volume. A crash is not a measurement -- None is."""
        edges = _clique("core", 5)
        edges["lonely/island.py"] = []
        graph = spectral.graph_from_edges(edges)
        report = spectral.conductance_report(
            graph, spectral.declared_partition(graph.nodes))
        rows = {r["package"]: r for r in report["rows"]}
        self.assertIsNone(rows["core"]["conductance_symmetric"])
        self.assertEqual(rows["core"]["leak_rate"], 0.0)


@unittest.skipUnless(spectral.HAVE_MATH, "math extra not installed")
class EigengapGroundTruth(unittest.TestCase):
    """4. Eigengap: a barbell has 2 clusters, planted-3 has 3."""

    def test_barbell_says_two_clusters(self):
        report = spectral.eigengap_report(_barbell())
        self.assertTrue(report["available"])
        self.assertEqual(report["clusters"], 2)
        self.assertTrue(report["confident"])

    def test_three_planted_communities_say_three_clusters(self):
        graph = ModularityGroundTruth._planted(k=3, n=8)
        report = spectral.eigengap_report(graph)
        self.assertEqual(report["clusters"], 3)
        self.assertTrue(report["confident"])

    def test_a_single_clique_is_one_cluster_not_hallucinated_structure(self):
        """GROUND TRUTH: a clique IS exactly one cluster. The metric must not
        invent a split just because it was asked for a number."""
        graph = spectral.graph_from_edges(_clique("flat", 12))
        report = spectral.eigengap_report(graph)
        self.assertEqual(report["clusters"], 1)
        self.assertTrue(report["confident"])

    def test_a_graph_with_no_natural_cluster_count_refuses_to_be_confident(self):
        """A 12-cycle has a smooth spectrum: every gap is the same, so the
        'largest gap' is a coin flip. ``confident`` is what stops that k
        becoming a claim -- without it this metric is astrology."""
        import networkx as nx
        report = spectral.eigengap_report(nx.cycle_graph(12))
        self.assertFalse(report["confident"])
        self.assertEqual(report["gap"], report["runner_up_gap"])

    def test_disconnected_graph_counts_components_instead_of_reading_noise(self):
        """GROUND TRUTH: 3 disjoint cliques = 3 clusters, by theorem (the
        multiplicity of eigenvalue 0 is the component count).

        Regression: the first real repo reading returned clusters=6 with
        gap=0.0 from a 25-component graph -- a k derived from float rounding
        error in a run of zeros. That is precisely the numerology this module
        exists to prevent, so it is pinned here.
        """
        edges = {**_clique("a", 5), **_clique("b", 5), **_clique("c", 5)}
        report = spectral.eigengap_report(spectral.graph_from_edges(edges))
        self.assertEqual(report["connected_components"], 3)
        self.assertEqual(report["clusters"], 3)
        self.assertTrue(report["confident"])
        self.assertIn("theorem", report["basis"])
        self.assertEqual(report["gap"], 0.0)

    def test_declared_count_comparison_names_the_direction_of_the_mismatch(self):
        graph = _barbell()
        over = spectral.eigengap_report(graph, declared_blocks=20)
        self.assertEqual(over["reads_as"],
                         "we declare more boundaries than the graph supports")
        under = spectral.eigengap_report(graph, declared_blocks=2)
        self.assertEqual(under["reads_as"], "granularity matches")


@unittest.skipUnless(spectral.HAVE_MATH, "math extra not installed")
class ReportPlumbing(unittest.TestCase):

    def test_graph_from_reach_drops_edges_to_unscanned_modules(self):
        """An import of something outside the tree is a real fact but not a
        node; inventing one would inflate every denominator."""

        class _Facts:
            def __init__(self, module, imports):
                self.module, self.imports = module, imports

        class _Report:
            modules = (_Facts("a/x.py", ("a/y.py", "third_party/z.py")),
                       _Facts("a/y.py", ()))

        graph = spectral.graph_from_reach(_Report())
        self.assertEqual(sorted(graph.nodes), ["a/x.py", "a/y.py"])
        self.assertEqual(graph.number_of_edges(), 1)

    def test_self_import_is_not_an_edge(self):
        graph = spectral.graph_from_edges({"a/x.py": ["a/x.py", "a/y.py"]})
        self.assertEqual(graph.number_of_edges(), 1)
        self.assertEqual(sorted(graph.nodes), ["a/x.py", "a/y.py"])

    def test_analyse_over_a_supplied_graph_needs_no_repo_pass(self):
        reading = spectral.analyse(graph=_barbell())
        self.assertTrue(reading["available"])
        self.assertEqual(reading["graph_source"], "graph")
        self.assertEqual(reading["nodes"], 20)
        self.assertEqual(reading["eigengap"]["clusters"], 2)
        self.assertTrue(reading["modularity"]["beats_random"])

    def test_scope_prefixes_filter_the_reach_report_and_are_echoed(self):
        """A reading must carry what it was taken over, or it can be quoted as
        a different reading."""

        class _Facts:
            def __init__(self, module, imports):
                self.module, self.imports = module, imports

        class _Report:
            modules = (_Facts("daedalus/a.py", ("daedalus/b.py",)),
                       _Facts("daedalus/b.py", ()),
                       _Facts("tests/test_a.py", ("daedalus/a.py",)))

        everything = spectral.graph_from_reach(_Report())
        self.assertEqual(everything.number_of_nodes(), 3)
        scoped = spectral.graph_from_reach(_Report(), scope_prefixes=("daedalus/",))
        self.assertEqual(sorted(scoped.nodes), ["daedalus/a.py", "daedalus/b.py"])
        # the edge INTO the excluded module is dropped, not left dangling
        self.assertEqual(scoped.number_of_edges(), 1)
        reading = spectral.analyse(report=_Report(), scope_prefixes=("daedalus/",))
        self.assertEqual(reading["scope"], ["daedalus/"])
        self.assertEqual(reading["nodes"], 2)

    def test_default_scope_hides_nothing(self):
        reading = spectral.analyse(graph=_barbell())
        self.assertEqual(reading["scope"], "whole repo")

    def test_scope_prefixes_with_a_prebuilt_graph_refuses_rather_than_lies(self):
        out = spectral.analyse(graph=_barbell(), scope_prefixes=("left/",))
        self.assertFalse(out["available"])
        self.assertIn("pre-built graph", out["reason"])

    def test_analyse_without_any_source_refuses_instead_of_guessing(self):
        reading = spectral.analyse()
        self.assertFalse(reading["available"])
        self.assertIn("no graph", reading["reason"])

    def test_spectral_evidence_covers_islands_with_none_not_zero(self):
        """The picker asks about ISLANDS. An island is off the Fiedler scope, so
        its fiedler value must be None (not measured) while its package-level
        numbers still arrive -- an enrichment that goes blank where it is needed
        is worse than none."""
        edges = _clique("core", 8)
        edges["lonely/island.py"] = []
        reading = spectral.analyse(graph=spectral.graph_from_edges(edges))
        rows = spectral.spectral_evidence(reading)
        self.assertIn("lonely/island.py", rows)
        row = rows["lonely/island.py"]
        self.assertIsNone(row["spectral_fiedler_value"])
        self.assertEqual(row["spectral_package"], "lonely")
        self.assertIn("core/m0.py", rows)
        self.assertIsNotNone(rows["core/m0.py"]["spectral_fiedler_value"])

    def test_spectral_evidence_of_an_unavailable_reading_is_empty(self):
        self.assertEqual(spectral.spectral_evidence({"available": False}), {})

    def test_no_threshold_constant_can_block_anything(self):
        """Guard on the standing invariant: this module is evidence, never a
        gate. Nothing in it may raise SystemExit or return an exit code."""
        import inspect
        source = inspect.getsource(spectral)
        self.assertNotIn("SystemExit", source)
        self.assertNotIn("sys.exit", source)


class MathUnavailable(unittest.TestCase):
    """Degrading honestly when the 'math' extra is absent."""

    def test_every_metric_reports_unavailable_with_the_extra_named(self):
        import unittest.mock as mock
        with mock.patch.object(spectral, "HAVE_MATH", False):
            for call in (lambda: spectral.fiedler_report(None),
                         lambda: spectral.modularity_report(None, {}),
                         lambda: spectral.conductance_report(None, {}),
                         lambda: spectral.eigengap_report(None),
                         lambda: spectral.analyse(graph=None)):
                out = call()
                self.assertFalse(out["available"])
                self.assertIn("math", out["reason"])


if __name__ == "__main__":
    unittest.main()
