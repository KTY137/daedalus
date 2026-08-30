# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Movement I — structcore: multi-language clone index + safety fencing.

Runs stdlib-only (no tree-sitter/lizard required). Python clones are detected at
unit level; cross-language copy-paste is detected at window level; any cluster
touching a SAFETY-CLASS path is fenced.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index, backend_status


# A ~6-line function, byte-identical everywhere it's planted (a Type-1 clone).
JOIN_WORKER = '''\
def join_worker(self):
    if self.thread is not None:
        self.thread.quit()
        self.thread.wait(2000)
        self.thread = None
        self.worker = None
'''

RAMP_DOWN = '''\
def ramp_down(self):
    for ch in self.channels:
        ch.set_voltage(0.0)
        ch.wait_settled()
        ch.disable()
'''

# A >=6 normalized-line block shared verbatim by two JS files (window clone).
JS_BLOCK = '''\
export function formatStatus(state) {
  const label = state.label || 'unknown';
  const color = state.ok ? 'green' : 'red';
  const icon = state.busy ? 'spinner' : 'dot';
  const badge = `${icon}-${color}`;
  return { label, color, icon, badge };
}
'''


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class StructcoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # safe Python clone (2 sites, no safety path)
        _write(self.root, "pkg/a.py", "import os\n\n" + JOIN_WORKER)
        _write(self.root, "pkg/b.py", "import sys\n\n" + JOIN_WORKER)
        # fenced Python clone (devices/ + hv path)
        _write(self.root, "devices/bias.py", RAMP_DOWN)
        _write(self.root, "controller/hv_ramp.py", RAMP_DOWN)
        # cross-file JS window clone
        _write(self.root, "web/x.js", "// x\n" + JS_BLOCK + "\nconst a = 1;\n")
        _write(self.root, "web/y.js", "// y\n" + JS_BLOCK + "\nconst b = 2;\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_languages_detected(self):
        langs = self.idx["languages"]
        self.assertIn("python", langs)
        self.assertIn("javascript", langs)

    def test_python_unit_clone_found(self):
        clusters = self.idx["duplication"]["unit_clusters"]
        names = {c["name"] for c in clusters}
        self.assertIn("join_worker", names)
        jw = next(c for c in clusters if c["name"] == "join_worker")
        self.assertEqual(jw["count"], 2)
        self.assertIsNone(jw["safety"])  # not a safety path -> collapsible

    def test_safety_class_clone_is_fenced(self):
        clusters = self.idx["duplication"]["unit_clusters"]
        rd = next(c for c in clusters if c["name"] == "ramp_down")
        self.assertEqual(rd["count"], 2)
        self.assertIsNotNone(rd["safety"])          # devices/ + hv -> fenced
        self.assertIn("do NOT auto-collapse", rd["safety"])

    def test_window_clone_across_js_files(self):
        wins = self.idx["duplication"]["window_clusters"]
        self.assertTrue(wins, "expected at least one window cluster")
        shared = {tuple(c["files"]) for c in wins}
        self.assertIn(("web/x.js", "web/y.js"), shared)

    def test_backend_status_shape(self):
        b = backend_status()
        self.assertIn("tree_sitter", b)
        self.assertIn("lizard", b)
        self.assertIsInstance(b["tree_sitter"], bool)

    def test_degrades_without_optional_deps(self):
        # The index must be produced regardless of optional engines.
        self.assertGreaterEqual(self.idx["n_files"], 6)
        self.assertIn("hotspots", self.idx)


if __name__ == "__main__":
    unittest.main()
