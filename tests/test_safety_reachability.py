"""Safety-class reachability: the fence must ask the import graph, not just the
edited path string.

``sensitivity.change_risk`` substring-matches the LITERAL paths it is handed.
That answers "is this file dangerous?" and never "does this file FEED something
dangerous?" -- so editing ``utils/clamp.py``, which ``controller/hv_interlock.py``
transitively imports, scored "low" and handed the local 7B bench write rights on
code a hardware interlock depends on. ``test_the_gap_is_real`` pins that
vulnerability so nobody deletes the fix believing the base check covered it.

The router now runs a blast-radius pre-check when (and only when) it is given a
``repo_root``. Everything here is paired: the BLOCKED case and the ALLOWED case,
plus the additivity proof that a caller who passes no ``repo_root`` gets exactly
what it got before.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from daedalus.provider_router import (FENCE_DOMINANCE_MIN_SAMPLE,
                                      FENCE_DOMINANCE_THRESHOLD,
                                      select_provider)
from daedalus.sensitivity import GENERIC_HIGH_RISK_PATHS, change_risk
from daedalus.structcore.graph import (fenced_dominance, fenced_fragment,
                                       fenced_reachability)
from daedalus.structcore.index import build_index, cached_index

# external_ok so the decision actually reaches the risk rules; a trusted-only
# role never leaves Claude anyway and would prove nothing.
CODER = {"name": "coder", "external_ok": True}
# Only the local bench up, so the un-escalated baseline is unambiguously
# "ollama / write" whether or not the path classifies as sensitive.
AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}
# No high/mid-risk term and no review-only term: the WORDING must contribute
# nothing, or the test would pass for the wrong reason.
OBJECTIVE = "Adjust the clamp helper defaults"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _chain_repo(tmp: str) -> Path:
    """utils/clamp.py <- lib/mid.py <- controller/hv_interlock.py."""
    root = Path(tmp) / "chain"
    _write(root, "utils/clamp.py",
           "def clamp(v, lo, hi):\n    return max(lo, min(hi, v))\n")
    _write(root, "lib/mid.py",
           "from utils.clamp import clamp\n\n\ndef scale(v):\n    return clamp(v, 0, 10)\n")
    _write(root, "controller/hv_interlock.py",
           "from lib.mid import scale\n\n\ndef trip(v):\n    return scale(v) > 5\n")
    # An island with no edge to the chain: proves the fence discriminates.
    _write(root, "docs/notes_helper.py", "def blurb():\n    return 'hi'\n")
    return root


class ReachabilityHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = _chain_repo(self.tmp.name)
        self.idx = build_index(str(self.root))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bfs_finds_fenced_node_with_hop_count_and_chain(self):
        r = fenced_reachability(self.idx, "utils/clamp.py", GENERIC_HIGH_RISK_PATHS)
        self.assertTrue(r["reaches"])
        self.assertEqual(r["hops"], 2)
        self.assertEqual(r["fenced_node"], "controller/hv_interlock.py")
        self.assertEqual(r["chain"], ["utils/clamp.py", "lib/mid.py",
                                      "controller/hv_interlock.py"])
        self.assertEqual(
            r["via"], "utils/clamp.py -> lib/mid.py -> controller/hv_interlock.py")
        self.assertTrue(r["known"])
        self.assertFalse(r["truncated"])

    def test_unconnected_module_does_not_reach(self):
        r = fenced_reachability(self.idx, "docs/notes_helper.py",
                                GENERIC_HIGH_RISK_PATHS)
        self.assertFalse(r["reaches"])
        self.assertIsNone(r["hops"])
        self.assertEqual(r["chain"], [])

    def test_fenced_path_itself_is_hop_zero(self):
        r = fenced_reachability(self.idx, "controller/hv_interlock.py",
                                GENERIC_HIGH_RISK_PATHS)
        self.assertEqual(r["hops"], 0)
        self.assertEqual(r["chain"], ["controller/hv_interlock.py"])

    def test_unknown_path_is_reported_not_guessed(self):
        r = fenced_reachability(self.idx, "nowhere/new_file.py",
                                GENERIC_HIGH_RISK_PATHS)
        self.assertFalse(r["known"])
        self.assertFalse(r["reaches"])

    def test_root_anchored_fragments_match_top_level_trees(self):
        # '/controller' cannot appear in the bare rel 'controller/x.py'; the
        # helper anchors the path so a top-level fenced tree is still caught.
        self.assertEqual(fenced_fragment("controller/x.py", GENERIC_HIGH_RISK_PATHS),
                         "/controller")
        self.assertIsNone(fenced_fragment("utils/clamp.py", GENERIC_HIGH_RISK_PATHS))

    def test_cycle_terminates(self):
        idx = {
            "modules": {"a.py": {}, "b.py": {}, "controller/c.py": {}},
            "import_edges": {"a.py": ["b.py"], "b.py": ["a.py"]},
            "import_edges_reverse": {"a.py": ["b.py"], "b.py": ["a.py"]},
        }
        r = fenced_reachability(idx, "a.py", GENERIC_HIGH_RISK_PATHS)
        self.assertFalse(r["reaches"])
        self.assertFalse(r["truncated"])
        self.assertEqual(r["visited"], 2)

    def test_visit_cap_truncates_instead_of_running_away(self):
        rev = {f"n{i}.py": [f"n{i + 1}.py"] for i in range(200)}
        idx = {"modules": {k: {} for k in rev}, "import_edges": {},
               "import_edges_reverse": rev}
        r = fenced_reachability(idx, "n0.py", GENERIC_HIGH_RISK_PATHS, visit_cap=10)
        self.assertTrue(r["truncated"])
        self.assertFalse(r["reaches"])


class GapIsRealTests(unittest.TestCase):
    """Documents the vulnerability the router change closes."""

    def test_the_gap_is_real(self):
        # The literal fence sees nothing wrong with the leaf...
        self.assertEqual(change_risk(OBJECTIVE, ["utils/clamp.py"]), "low")
        # ...while the very module it feeds is fenced on its own path.
        self.assertEqual(
            change_risk(OBJECTIVE, ["controller/hv_interlock.py"]), "high")


class SelectProviderFenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = _chain_repo(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_without_repo_root_behaviour_is_unchanged(self):
        d = select_provider(CODER, OBJECTIVE, ["utils/clamp.py"], AVAIL)
        self.assertEqual(d.risk, "low")
        self.assertEqual(d.provider, "ollama")
        self.assertEqual(d.mode, "write")
        self.assertIsNone(d.reachability)
        # The serialised shape a caller sees must not have grown either.
        self.assertEqual(sorted(d.as_dict()), sorted(
            ["provider", "mode", "persona", "reason", "sensitive", "risk", "culture"]))

    def test_with_repo_root_the_leaf_edit_is_forced_to_the_trusted_lane(self):
        d = select_provider(CODER, OBJECTIVE, ["utils/clamp.py"], AVAIL,
                            repo_root=str(self.root))
        self.assertEqual(d.provider, "claude_cli")
        self.assertEqual(d.risk, "high")
        self.assertIn("controller/hv_interlock.py", d.reason)
        self.assertIn("utils/clamp.py -> lib/mid.py", d.reason)
        self.assertEqual(d.reachability["hops"], 2)
        self.assertIn("reachability", d.as_dict())

    def test_absolute_path_is_mapped_onto_the_index_and_still_blocked(self):
        abs_path = str(self.root / "utils" / "clamp.py")
        d = select_provider(CODER, OBJECTIVE, [abs_path], AVAIL,
                            repo_root=str(self.root))
        self.assertEqual(d.provider, "claude_cli")
        self.assertTrue(d.reachability["escalate"])

    def test_unconnected_module_still_gets_the_cheap_lane(self):
        # The ALLOW half: the fence must not simply escalate everything.
        d = select_provider(CODER, OBJECTIVE, ["docs/notes_helper.py"], AVAIL,
                            repo_root=str(self.root))
        self.assertEqual(d.provider, "ollama")
        self.assertEqual(d.mode, "write")
        self.assertEqual(d.risk, "low")
        self.assertFalse(d.reachability["escalate"])

    def test_case_and_dot_spellings_do_not_slip_past_the_fence(self):
        for spelling in ("./utils/clamp.py", "Utils/Clamp.py",
                         "utils\\clamp.py", "lib/../utils/clamp.py"):
            with self.subTest(spelling=spelling):
                d = select_provider(CODER, OBJECTIVE, [spelling], AVAIL,
                                    repo_root=str(self.root))
                self.assertEqual(d.provider, "claude_cli", spelling)
                self.assertEqual(d.reachability["hops"], 2)

    def test_empty_index_is_reported_never_silent(self):
        # Pointing at a non-repo does NOT raise -- it yields an index with no
        # modules, where every lookup reads as "no dependents". Nothing is
        # reachable in an empty graph, so this alone does not escalate, but it
        # must be visible rather than presented as a clean bill of health.
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        d = select_provider(CODER, OBJECTIVE, ["notes/whatever.txt"], AVAIL,
                            repo_root=str(empty))
        self.assertEqual(d.reachability["error"], "index contains no modules")
        self.assertFalse(d.reachability["escalate"])

    def test_empty_index_still_fails_closed_on_a_real_source_file(self):
        # The half that matters: the graph is empty but the file is real Python
        # sitting on disk, so its dependents are unknown, not absent.
        empty = Path(self.tmp.name) / "empty2"
        (empty / "utils").mkdir(parents=True)
        _write(empty, "utils/clamp.py", "def clamp(v):\n    return v\n")
        d = select_provider(CODER, OBJECTIVE, ["utils/clamp.py"], AVAIL,
                            idx={"root": str(empty), "modules": {},
                                 "import_edges": {}, "import_edges_reverse": {}},
                            repo_root=str(empty))
        self.assertEqual(d.provider, "claude_cli")
        self.assertTrue(d.reachability["escalate"])
        self.assertIn("absent from the blast-radius graph", d.reason)

    def test_index_build_failure_fails_closed(self):
        class _Boom(dict):
            def get(self, *a, **k):
                raise RuntimeError("index backend exploded")

        # An index we cannot interrogate is an unknown answer, and an unknown
        # answer must not be a pass.
        d = select_provider(CODER, OBJECTIVE, ["utils/clamp.py"], AVAIL,
                            repo_root=str(self.root), idx=_Boom())
        self.assertEqual(d.provider, "claude_cli")
        self.assertTrue(d.reachability["escalate"])
        self.assertIn("index unavailable", d.reason)

    def test_unindexed_source_that_exists_on_disk_fails_closed(self):
        # A mis-scoped repo_root: the file is real Python, but this index does
        # not contain it, so its dependents are unknown.
        other = Path(self.tmp.name) / "outside"
        _write(other, "sneaky.py", "def go():\n    return 1\n")
        d = select_provider(CODER, OBJECTIVE, [str(other / "sneaky.py")], AVAIL,
                            repo_root=str(self.root))
        self.assertEqual(d.provider, "claude_cli")
        self.assertTrue(d.reachability["escalate"])
        self.assertIn("absent from the blast-radius graph", d.reason)

    def test_non_source_and_not_yet_created_paths_keep_the_cheap_lane(self):
        # The ALLOW half of the previous test: a doc file and a file that does
        # not exist yet genuinely have no dependents.
        _write(self.root, "README.md", "hello\n")
        d = select_provider(CODER, OBJECTIVE, ["README.md", "utils/brand_new.py"],
                            AVAIL, repo_root=str(self.root))
        self.assertEqual(d.provider, "ollama")
        self.assertFalse(d.reachability["escalate"])
        self.assertEqual(d.reachability["unresolved"],
                         ["README.md", "utils/brand_new.py"])


class DominanceGuardrailTests(unittest.TestCase):
    """When nearly every editable module feeds the fence, "reaches the fence"
    carries no information; the check stands down to path-local risk and REPORTS
    that it did."""

    def _dominant_idx(self, n: int) -> dict:
        # n leaves, each imported by the fenced controller -> every candidate
        # reaches the fence.
        fenced = "controller/hv_interlock.py"
        leaves = [f"utils/leaf{i:03d}.py" for i in range(n)]
        return {
            "modules": {m: {} for m in [fenced] + leaves},
            "import_edges": {fenced: sorted(leaves)},
            "import_edges_reverse": {m: [fenced] for m in leaves},
        }

    def test_dominance_fraction_counts_only_non_fenced_candidates(self):
        dom = fenced_dominance(self._dominant_idx(24), GENERIC_HIGH_RISK_PATHS)
        self.assertEqual(dom["candidates"], 24)
        self.assertEqual(dom["escalated"], 24)
        self.assertEqual(dom["fenced_nodes"], 1)
        self.assertEqual(dom["fraction"], 1.0)

    def test_fallback_to_path_local_and_it_is_observable(self):
        idx = self._dominant_idx(FENCE_DOMINANCE_MIN_SAMPLE + 4)
        d = select_provider(CODER, OBJECTIVE, ["utils/leaf000.py"], AVAIL, idx=idx)
        self.assertEqual(d.risk, "low")          # path-local verdict, as before
        self.assertEqual(d.provider, "ollama")
        self.assertTrue(d.reachability["dominance"]["fallback"])
        self.assertFalse(d.reachability["escalate"])
        self.assertIn("fence dominates", d.reachability["reason"])
        self.assertGreater(d.reachability["dominance"]["fraction"],
                           FENCE_DOMINANCE_THRESHOLD)

    def test_small_repo_is_below_the_sample_floor_so_the_fence_stays_up(self):
        idx = self._dominant_idx(3)
        d = select_provider(CODER, OBJECTIVE, ["utils/leaf000.py"], AVAIL, idx=idx)
        self.assertFalse(d.reachability["dominance"]["fallback"])
        self.assertTrue(d.reachability["escalate"])
        self.assertEqual(d.provider, "claude_cli")

    def test_a_fenced_path_still_escalates_under_the_fallback(self):
        # The fallback must never lower the floor: path-local risk still fires.
        idx = self._dominant_idx(FENCE_DOMINANCE_MIN_SAMPLE + 4)
        d = select_provider(CODER, OBJECTIVE, ["controller/hv_interlock.py"],
                            AVAIL, idx=idx)
        self.assertEqual(d.risk, "high")
        self.assertEqual(d.provider, "claude_cli")


class DeterminismTests(unittest.TestCase):
    """Two processes must block the same edit with the SAME chain, or the
    explanation an operator sees changes run to run."""

    def test_reported_chain_is_stable_across_hash_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _chain_repo(tmp)
            # A diamond: two equally-short routes to the fence, so an unstable
            # tie-break would show up as a different reported chain.
            _write(root, "lib/other.py",
                   "from utils.clamp import clamp\n\n\ndef alt(v):\n    return clamp(v, 1, 2)\n")
            _write(root, "controller/hv_interlock.py",
                   "from lib.mid import scale\nfrom lib.other import alt\n\n\n"
                   "def trip(v):\n    return scale(v) > alt(v)\n")
            prog = (
                "import json,sys\n"
                "from daedalus.structcore.index import build_index\n"
                "from daedalus.structcore.graph import fenced_reachability\n"
                "from daedalus.sensitivity import GENERIC_HIGH_RISK_PATHS as F\n"
                "idx = build_index(sys.argv[1])\n"
                "r = fenced_reachability(idx, 'utils/clamp.py', F)\n"
                "print(json.dumps(r, sort_keys=True))\n"
            )
            outs = []
            for seed in ("0", "1", "12345", "99991"):
                env = dict(os.environ, PYTHONHASHSEED=seed)
                p = subprocess.run([sys.executable, "-c", prog, str(root)],
                                   capture_output=True, text=True, env=env,
                                   cwd=str(Path(__file__).resolve().parent.parent))
                self.assertEqual(p.returncode, 0, p.stderr)
                outs.append(json.loads(p.stdout.strip().splitlines()[-1]))
            for other in outs[1:]:
                self.assertEqual(outs[0], other,
                                 "reported blast-radius chain varies with PYTHONHASHSEED")
            self.assertTrue(outs[0]["reaches"])


class LiveMutatePathTests(unittest.TestCase):
    """``route_and_select`` is what ``offload`` calls; if repo_root stopped at
    ``route_task`` the fence would exist but never run on the live path."""

    def test_route_and_select_threads_repo_root_into_the_fence(self):
        from daedalus.provider_router import route_and_select
        with tempfile.TemporaryDirectory() as tmp:
            root = _chain_repo(tmp)
            cached_index(str(root))
            _, d = route_and_select(OBJECTIVE, ["utils/clamp.py"], AVAIL,
                                    repo_root=str(root))
            # Which role stage 1 picks is not this test's business; that the
            # fence RAN and took the local write lane away is.
            self.assertEqual(d.provider, "claude_cli")
            self.assertEqual(d.risk, "high")
            self.assertTrue(d.reachability["escalate"])
            self.assertIn("hv_interlock", d.reachability["reason"])

    def test_route_and_select_without_repo_root_is_unchanged(self):
        from daedalus.provider_router import route_and_select
        _, d = route_and_select(OBJECTIVE, ["utils/clamp.py"], AVAIL)
        self.assertIsNone(d.reachability)
        self.assertEqual(d.risk, "low")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
