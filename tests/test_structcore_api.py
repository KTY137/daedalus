"""Mythic connection — structure_summary shape + symbol-level (graph) slicing.

Covers the data the /api/structure and /api/distill endpoints serve, without
standing up the HTTP server (the handler is a thin wrapper over these).
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index, semantic_slice
from daedalus.structcore.report import structure_summary


CLONE = "def dup(a, b):\n    total = a + b\n    total = total * 2\n    return total\n"
UTIL = "def compute(x):\n    return x + 100\n"
CORE = "from proj import util\n\n\ndef run():\n    return util.compute(5)\n"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class StructureSummaryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/a.py", CLONE)
        _write(self.root, "devices/b.py", CLONE)  # same clone under a safety path
        self.summary = structure_summary(build_index(self.root))

    def tearDown(self):
        self._tmp.cleanup()

    def test_summary_shape(self):
        for key in ("backend", "repo_root", "n_files", "languages", "totals",
                    "hotspots", "clones", "window_clones", "fan_in"):
            self.assertIn(key, self.summary)
        self.assertIn("python", self.summary["languages"])

    def test_clone_and_safety_totals(self):
        self.assertGreaterEqual(self.summary["totals"]["unit_clusters"], 1)
        dup = next(c for c in self.summary["clones"] if c["name"] == "dup")
        self.assertEqual(dup["count"], 2)
        self.assertIsNotNone(dup["safety"])  # devices/ path -> fenced
        self.assertGreaterEqual(self.summary["totals"]["safety_fenced"], 1)


class SymbolGraphSliceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/util.py", UTIL)
        _write(self.root, "proj/core.py", CORE)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_symbol_slice_pulls_callee_body(self):
        res = semantic_slice(self.root, "proj/core.py::run", idx=self.idx)
        roles = {i["role"] for i in res["included"]}
        self.assertIn("callee", roles)                      # compute() pulled in
        self.assertIn("def compute", res["slice_text"])     # its body, in full
        self.assertEqual(res["focus_symbol"], "run")


if __name__ == "__main__":
    unittest.main()
