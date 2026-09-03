"""Movement I.5 / Moves 2 + 4 — all-language dependency graph + sharper symbols.

Move 2: Java/Rust/JS internal imports resolve to real dependency edges + fan-in
(needs tree-sitter for precise import nodes; skipped gracefully if absent).

Move 4: the import/scope-aware symbol resolver routes a call to the IMPORTED
definition instead of every same-named unit — a pure-Python check that needs no
optional backend.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.eval.tasks import AGENT_ENV_ROOT
from daedalus.structcore import build_index
from daedalus.structcore.index import resolution_context
from daedalus.structcore import graph
from daedalus.structcore.parse import tree_sitter_available, extract_units
from daedalus.structcore.languages import spec_for


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@unittest.skipUnless(tree_sitter_available(),
                     "tree-sitter not installed -> non-Python import edges degrade")
class MultiLanguageImportsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Java: import app.util.Helper -> src/app/util/Helper.java
        _write(self.root, "src/app/Main.java",
               "package app;\nimport app.util.Helper;\nclass Main { }\n")
        _write(self.root, "src/app/util/Helper.java",
               "package app.util;\nclass Helper { }\n")
        # Rust: use crate::util::helper -> util.rs
        _write(self.root, "rustpkg/main.rs", "use crate::util::helper;\nfn main() { }\n")
        _write(self.root, "rustpkg/util.rs", "pub fn helper() { }\n")
        # JS: import from './util' -> web/util.js
        _write(self.root, "web/app.js",
               "import { help } from './util';\nexport function app() { return help(); }\n")
        _write(self.root, "web/util.js", "export function help() { return 1; }\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_java_edge(self):
        deps = self.idx["dependencies"]
        self.assertIn("src/app/util/Helper.java", deps.get("src/app/Main.java", []))

    def test_rust_edge(self):
        deps = self.idx["dependencies"]
        self.assertIn("rustpkg/util.rs", deps.get("rustpkg/main.rs", []))

    def test_js_edge(self):
        deps = self.idx["dependencies"]
        self.assertIn("web/util.js", deps.get("web/app.js", []))

    def test_fan_in_counts_targets(self):
        fan = self.idx["fan_in"]
        self.assertEqual(fan.get("src/app/util/Helper.java"), 1)
        self.assertEqual(fan.get("rustpkg/util.rs"), 1)
        self.assertEqual(fan.get("web/util.js"), 1)


class SymbolResolverTest(unittest.TestCase):
    """Two unrelated modules both define ``process``; ``main`` imports only one
    and calls ``process``. Resolution must pick the imported one, not both."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/svc_a.py", "def process(x):\n    return x + 1\n")
        _write(self.root, "proj/svc_b.py", "def process(x):\n    return x - 1\n")
        _write(self.root, "proj/main.py",
               "from proj import svc_a\n\n\ndef run():\n    return svc_a.process(3)\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _units(self, rel):
        text = (self.root / rel).read_text(encoding="utf-8")
        return extract_units(rel, text, spec_for(rel))

    def test_resolver_routes_to_imported_definition(self):
        run = next(u for u in self._units("proj/main.py") if u.name == "run")
        candidates = self._units("proj/svc_a.py") + self._units("proj/svc_b.py")

        # Pure name-match (v1): ambiguous -> BOTH process() units match.
        naive = graph.callees(run, candidates)
        self.assertEqual({u.module for u in naive},
                         {"proj/svc_a.py", "proj/svc_b.py"})

        # Import/scope-aware (Move 4): resolves to the imported module only.
        resolver = resolution_context(self.root)
        self.assertIsNotNone(resolver)
        sharp = graph.callees(run, candidates, resolver)
        self.assertEqual([u.module for u in sharp], ["proj/svc_a.py"])

    def test_resolver_defaults_preserve_v1_behavior(self):
        # No resolver arg -> identical to the historical name-match.
        run = next(u for u in self._units("proj/main.py") if u.name == "run")
        cands = self._units("proj/svc_a.py")
        self.assertEqual(graph.callees(run, cands),
                         graph.callees(run, cands, None))


if __name__ == "__main__":
    unittest.main()


class StructcoreCanSeeItsOwnCycles(unittest.TestCase):
    """THE THERMOMETER for the 2026-07-30 audit finding (Aristaeus, P0).

    Before: ``structcore`` reported **0 of 3** non-trivial strongly connected
    components in this repo's own import graph, because it had no cycle detection
    at all. ``topology.spectral_partition`` builds ``nx.Graph()`` -- an
    undirected projection, by its own label -- and direction is the only thing a
    cycle is made of. ``graph.py``'s ``seen`` set is a walk guard, not a detector.

    The consequence was not a missing feature but a missing ANSWER: the tool whose
    job is "what should I distill?" could not find the largest structural knot in
    the tree it was pointed at, and the 13-module component had to be derived by a
    throwaway script the product does not ship.

    These tests assert the capability, not the current shape of this repo, with
    one deliberate exception noted below.
    """

    def test_a_two_cycle_is_found(self):
        from daedalus.structcore import nontrivial_components
        comps = nontrivial_components({"a": ["b"], "b": ["a"], "c": ["a"]})
        self.assertEqual(comps, (("a", "b"),))

    def test_a_dag_has_no_cyclic_components(self):
        from daedalus.structcore import nontrivial_components
        self.assertEqual(
            nontrivial_components({"a": ["b", "c"], "b": ["d"], "c": ["d"]}), ())

    def test_a_module_only_ever_imported_still_counts_as_a_component(self):
        # Every target is a node too. Otherwise the component count would depend
        # on which side of an edge a module happens to sit.
        from daedalus.structcore import strongly_connected_components
        comps = strongly_connected_components({"a": ["b"]})
        self.assertEqual(comps, (("a",), ("b",)))

    def test_a_self_import_is_reported_and_not_mistaken_for_a_leaf(self):
        from daedalus.structcore import nontrivial_components, self_loops
        edges = {"a": ["a"], "b": ["c"], "c": []}
        self.assertEqual(self_loops(edges), ("a",))
        self.assertEqual(nontrivial_components(edges), (("a",),))

    def test_the_output_is_deterministic_and_ordered_largest_first(self):
        # These results get committed to receipts and diffed between runs, so set
        # iteration order is not an acceptable basis for them.
        from daedalus.structcore import strongly_connected_components
        edges = {"x": ["y"], "y": ["x"], "p": ["q"], "q": ["r"], "r": ["p"],
                 "z": []}
        first = strongly_connected_components(edges)
        self.assertEqual(first, strongly_connected_components(dict(reversed(
            list(edges.items())))))
        sizes = [len(c) for c in first]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_deep_chains_do_not_blow_the_stack(self):
        # Iterative Tarjan on purpose: a recursive version would raise
        # RecursionError as the repo grew, and it would surface as a crash in
        # whatever tool asked rather than here.
        from daedalus.structcore import nontrivial_components
        n = 4000
        edges = {f"m{i}": [f"m{i+1}"] for i in range(n)}
        edges[f"m{n}"] = ["m0"]                      # one giant cycle
        comps = nontrivial_components(edges)
        self.assertEqual(len(comps), 1)
        self.assertEqual(len(comps[0]), n + 1)

    def test_induced_edges_are_the_ones_a_cut_must_consider(self):
        from daedalus.structcore import component_edges
        edges = {"a": ["b", "outside"], "b": ["a"], "outside": []}
        self.assertEqual(component_edges(edges, ("a", "b")),
                         (("a", "b"), ("b", "a")))

    #: The cross-domain knot ``core.py`` sits in, pinned by MEMBERSHIP.
    #:
    #: UPDATED 2026-09-02 for packet G1-SCC-CUT1 (``6b557bd9``, merged
    #: ``22cff7bf``), which cut this component from 18 modules to 13 by making
    #: ``kernel/attempt_execution.py`` take an injected ``OffloadPort`` instead
    #: of importing the ``daedalus.offload`` WORKLOAD. The five modules that
    #: left are ``kernel/attempt_execution.py``, ``kernel/promotion.py``,
    #: ``spine/attempt.py``, ``spine/bootstrap.py`` and ``spine/picker.py`` --
    #: the whole kernel/spine layer. That is the deliberate, visible shrink the
    #: docstring below demands a record of; MEASURED at eb5228ac, 28 induced
    #: edges remain.
    CORE_CYCLE = frozenset({
        "daedalus/build.py",
        "daedalus/build_exec.py",
        "daedalus/core.py",
        "daedalus/doctor.py",
        "daedalus/file_bridge.py",
        "daedalus/health.py",
        "daedalus/orchestration/ikarus_supervisor.py",
        "daedalus/kairos/gated_writes.py",
        "daedalus/kairos/scheduler.py",
        "daedalus/offload.py",
        "daedalus/progress.py",
        "daedalus/progress_sources.py",
        "daedalus/status.py",
    })

    def test_this_repo_reports_its_own_cyclic_components(self):
        """The regression this file exists for.

        Asserts the CAPABILITY plus one fact about this repo: the component
        containing ``core.py`` is named, member by member. If a future
        distillation legitimately breaks it, this assertion should be UPDATED
        with the new membership and the commit that cut it -- the point is that
        shrinking it becomes a visible, deliberate act rather than something
        nobody can measure either way.

        LOCATED BY MEMBERSHIP, NOT BY ``components[0]`` (changed 2026-09-02).
        The old form asked for the LARGEST component and asserted ``core.py``
        was in it, which silently conflated two different claims. G1-SCC-CUT1
        cut this component 18 -> 13 and a pre-existing, untouched 14-module
        ``runtimes/provider_*`` cycle inherited the top slot, so the test went
        red for a cut that was exactly what the packet set out to do -- while
        the thing it meant to watch was still there, one row down. Indexing by
        size made an unrelated component's size a hidden input to this
        assertion. Membership is what it was always about.
        """
        from daedalus.structcore import cycle_report
        report = cycle_report(repo_root=str(AGENT_ENV_ROOT))
        self.assertGreaterEqual(
            report["n_cyclic_components"], 1,
            "structcore must be able to report the cycles in its own import "
            "graph; 0 means the detector regressed to the undirected lens")
        biggest = report["components"][0]
        self.assertGreaterEqual(biggest["size"], 2)
        self.assertTrue(biggest["induced_edges"])

        holding = [c for c in report["components"]
                   if "daedalus/core.py" in c["modules"]]
        self.assertEqual(
            len(holding), 1,
            "daedalus/core.py is in no cyclic component at all -- if a "
            "distillation genuinely made it acyclic that is a WIN, but this "
            "assertion has to be retired deliberately rather than by deleting "
            "the only thing pinning the knot's membership")
        self.assertEqual(
            frozenset(holding[0]["modules"]), self.CORE_CYCLE,
            "the cross-domain component around daedalus/core.py changed "
            "membership; UPDATE CORE_CYCLE with the new list and name the "
            "commit that moved it, per this test's docstring")
        # The induced edges are what any feedback-arc-set proposal is computed
        # from, so an empty list here would make every such proposal vacuous.
        self.assertTrue(holding[0]["induced_edges"])
