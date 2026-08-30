# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Movement I — 'Distill this': semantic slice beats whole-repo concatenation.

Verifies the slice includes the focus + its caller neighborhood, OMITS unrelated
files, and reports a real token reduction vs the naive full-repo dump.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import semantic_slice, build_index


CORE = '''\
def helper(x):
    """Return x doubled."""
    return x * 2


class Engine:
    def run(self):
        return helper(21)
'''

APP = '''\
from proj import core


def main():
    e = core.Engine()
    return e.run()
'''

# a big, unrelated file that a whole-repo dump would wastefully include
UNRELATED = "# unrelated module\nUNIQUE_MARKER = 'do-not-include'\n" + \
    "\n".join(f"def unrelated_{i}():\n    return {i}" for i in range(40))


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class SliceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        _write(self.root, "proj/app.py", APP)
        _write(self.root, "proj/unrelated.py", UNRELATED)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_focus_and_caller_included_unrelated_omitted(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        self.assertEqual(res["focus_file"], "proj/core.py")
        files = {i["file"]: i["role"] for i in res["included"]}
        self.assertEqual(files["proj/core.py"], "focus")
        self.assertEqual(files.get("proj/app.py"), "caller")  # app imports core
        self.assertNotIn("proj/unrelated.py", files)
        self.assertNotIn("UNIQUE_MARKER", res["slice_text"])

    def test_token_reduction_positive(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        self.assertLess(res["slice_tokens"], res["whole_repo_tokens"])
        self.assertGreater(res["reduction_pct"], 0)

    def test_symbol_level_focus(self):
        res = semantic_slice(self.root, "proj/core.py::helper", idx=self.idx)
        self.assertEqual(res["focus_symbol"], "helper")
        # focus is just the helper function, so Engine should not be in the FOCUS block
        focus_block = res["slice_text"].split("# =====", 2)[1]
        self.assertIn("def helper", focus_block)
        self.assertNotIn("class Engine", focus_block)

    def test_suffix_target_resolves(self):
        res = semantic_slice(self.root, "core.py", idx=self.idx)
        self.assertEqual(res["focus_file"], "proj/core.py")


C_UTIL_H = "int util_add(int a, int b);\nint util_sub(int a, int b);\n"
C_UTIL_C = '#include "util.h"\n\nint util_add(int a, int b) { return a + b; }\n' \
           "int util_sub(int a, int b) { return a - b; }\n"
C_MAIN_C = '#include "util.h"\n\nint main(void) { return util_add(1, 2); }\n'
C_HELPER_C = '#include "util.h"\n\nint helper(void) { return util_sub(9, 4); }\n'


class NonPythonSliceTest(unittest.TestCase):
    """S2: the neighborhood used to be computed from the python-only dotted
    module map, so a C/C++/QML/TS target expanded to NOTHING and the slice
    silently degraded to the focus file -- while ``import_edges`` held the
    correct rel->rel edges for every language the whole time."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "src/util.h", C_UTIL_H)
        _write(self.root, "src/util.c", C_UTIL_C)
        _write(self.root, "src/main.c", C_MAIN_C)
        _write(self.root, "src/helper.c", C_HELPER_C)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_c_neighborhood_expands_callers(self):
        res = semantic_slice(self.root, "src/util.h", idx=self.idx)
        callers = {i["file"] for i in res["included"] if i["role"] == "caller"}
        self.assertEqual(callers, {"src/util.c", "src/main.c", "src/helper.c"})
        self.assertEqual(res["n_included"], 4)

    def test_c_neighborhood_expands_dependencies(self):
        res = semantic_slice(self.root, "src/main.c", idx=self.idx)
        deps = {i["file"] for i in res["included"] if i["role"] == "dependency"}
        self.assertEqual(deps, {"src/util.h"})

    def test_no_shell_stops_when_no_shell(self):
        res = semantic_slice(self.root, "src/util.h", idx=self.idx)
        self.assertEqual(res["shell_boundary_stops"], 0)

    def test_slice_is_byte_identical_across_hashseed(self):
        """The caller set is a set; if any iteration reaching output skipped
        sorted(), PYTHONHASHSEED would reorder the slice text."""
        import json
        import os
        import subprocess
        import sys

        prog = (
            "import json,sys\n"
            "from daedalus.structcore.slice import semantic_slice\n"
            "out = {}\n"
            "for t in ('src/util.h', 'src/main.c'):\n"
            "    r = semantic_slice(sys.argv[1], t)\n"
            "    out[t] = {'t': r['slice_text'],\n"
            "              'f': [i['file'] for i in r['included']]}\n"
            "print(json.dumps(out))\n"
        )
        outs = []
        for seed in ("0", "1", "12345", "99991"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            p = subprocess.run([sys.executable, "-c", prog, str(self.root)],
                               capture_output=True, text=True, env=env,
                               cwd=str(Path(__file__).resolve().parent.parent))
            self.assertEqual(p.returncode, 0, p.stderr)
            outs.append(json.loads(p.stdout.strip().splitlines()[-1]))
        for other in outs[1:]:
            self.assertEqual(outs[0], other, "slice output varies with PYTHONHASHSEED")


class SliceDeterminismTest(unittest.TestCase):
    """graph.callees iterates ``identifiers()``, which is a SET, and that order
    reaches the CALLEES block of slice_text. Iterating it raw made symbol-level
    slices differ run-to-run. Pre-existing; caught while diffing S2."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/core.py", "def helper(x):\n    return x * 2\n")
        _write(self.root, "pkg/util.py", "def fmt(v):\n    return str(v)\n")
        _write(self.root, "pkg/app.py",
               "from pkg import core\nfrom pkg.util import fmt\n\n\n"
               "def main():\n    return fmt(core.helper(21))\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_symbol_slice_callee_order_stable_across_hashseed(self):
        import json
        import os
        import subprocess
        import sys

        prog = (
            "import json,sys\n"
            "from daedalus.structcore.slice import semantic_slice\n"
            "r = semantic_slice(sys.argv[1], 'pkg/app.py::main')\n"
            "print(json.dumps([i['file'] for i in r['included']]))\n"
        )
        seen = []
        for seed in ("0", "1", "12345", "99991"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            p = subprocess.run([sys.executable, "-c", prog, str(self.root)],
                               capture_output=True, text=True, env=env,
                               cwd=str(Path(__file__).resolve().parent.parent))
            self.assertEqual(p.returncode, 0, p.stderr)
            seen.append(json.loads(p.stdout.strip().splitlines()[-1]))
        # both callees must be present -- order fixed, nothing dropped
        self.assertEqual(set(seen[0]), {"pkg/app.py", "pkg/core.py", "pkg/util.py"})
        for other in seen[1:]:
            self.assertEqual(seen[0], other, "callee order varies with PYTHONHASHSEED")


_DEGRADE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)


def _chunky(mod_i: int) -> str:
    """A dep with 12 fat function signatures -> a non-trivial skeleton, so a tight
    token budget must actually shed whole neighbours."""
    return "\n\n".join(
        f"def {chr(97 + mod_i)}_function_number_{j}(argument_one, argument_two, "
        f"argument_three):\n    return argument_one + argument_two + {j}"
        for j in range(12)
    ) + "\n"


class SliceBudgetDegradeTest(unittest.TestCase):
    """max_tokens degrade (Momus rule 5): over budget, drop WHOLE neighbour units
    from lowest priority, ALWAYS keeping the FOCUS and the WITHHELD breadcrumb,
    with a visible TRIMMED marker. Never string-truncate (a tail cut would delete
    the anti-hallucination WITHHELD block)."""

    DEPS = [f"d{i}" for i in range(5)]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        imports = "".join(f"from proj import {d}\n" for d in self.DEPS)
        imports += "from proj import secret\n"
        body = "".join(f"    {d}.{chr(97 + i)}_function_number_0(1, 2, 3)\n"
                        for i, d in enumerate(self.DEPS))
        _write(self.root, "proj/focus.py", imports + "\n\ndef run():\n" + body)
        for i, d in enumerate(self.DEPS):
            _write(self.root, f"proj/{d}.py", _chunky(i))
        # a secret dependency -> withheld by the floor even on the trusted lane.
        _write(self.root, "proj/secret.py",
               "PRIVATE = '''" + _DEGRADE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_uncapped_is_byte_identical(self):
        a = semantic_slice(self.root, "proj/focus.py", idx=self.idx)
        b = semantic_slice(self.root, "proj/focus.py", idx=self.idx, max_tokens=None)
        self.assertEqual(a["slice_text"], b["slice_text"])
        self.assertEqual(a["n_included"], b["n_included"])
        self.assertEqual(a["trimmed_count"], 0)

    def test_over_budget_keeps_focus_and_withheld_drops_whole_neighbours(self):
        full = semantic_slice(self.root, "proj/focus.py", idx=self.idx)
        self.assertGreaterEqual(full["withheld_count"], 1)          # secret dep withheld
        n_neighbours = full["n_included"] - 1                       # minus the focus
        self.assertGreaterEqual(n_neighbours, 3)                    # several clean deps
        cap = full["slice_tokens"] // 3                             # forces a real trim
        res = semantic_slice(self.root, "proj/focus.py", idx=self.idx, max_tokens=cap)

        self.assertGreater(res["trimmed_count"], 0)                 # degrade exercised
        text = res["slice_text"]
        # FOCUS survives WHOLE (not truncated)
        self.assertIn("# ===== FOCUS: proj/focus.py =====", text)
        self.assertIn("def run():", text)
        # WITHHELD breadcrumb survives the trim -- the whole point
        self.assertIn("# ===== WITHHELD (egress gate) =====", text)
        self.assertIn("proj/secret.py", text)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", text)            # secret bytes never leak
        # honest, visible marker
        self.assertIn(f"dropped {res['trimmed_count']} of {n_neighbours}", text)
        # nothing was truncated AFTER the gate report: the marker is the last block
        self.assertTrue(text.rstrip().endswith("to fit budget ====="))
        # WHOLE units: included drops exactly trimmed_count neighbours...
        self.assertEqual(res["n_included"], full["n_included"] - res["trimmed_count"])
        # ...and each surviving dep contributes exactly one intact per-file
        # skeleton header (a "# path  (skeleton)" line; the section header ends in
        # "=====", so counting line-final "(skeleton)" isolates real units).
        kept_units = sum(1 for ln in text.splitlines()
                         if ln.rstrip().endswith("(skeleton)"))
        self.assertEqual(kept_units, n_neighbours - res["trimmed_count"])

    def test_tiny_cap_drops_all_neighbours_but_never_focus_or_withheld(self):
        full = semantic_slice(self.root, "proj/focus.py", idx=self.idx)
        n_neighbours = full["n_included"] - 1
        res = semantic_slice(self.root, "proj/focus.py", idx=self.idx, max_tokens=1)
        self.assertEqual(res["trimmed_count"], n_neighbours)        # all neighbours shed
        self.assertEqual(res["n_included"], 1)                      # focus only
        self.assertIn("# ===== FOCUS: proj/focus.py =====", res["slice_text"])
        self.assertIn("# ===== WITHHELD (egress gate) =====", res["slice_text"])
        self.assertNotIn("BEGIN RSA PRIVATE KEY", res["slice_text"])


if __name__ == "__main__":
    unittest.main()
