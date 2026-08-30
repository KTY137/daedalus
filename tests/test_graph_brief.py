# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""daedalus.lanes.graph_brief -- the threefold graph as a prompt a model reads.

MEASURED 2026-07-30: no provider module referenced structcore/build_index/
typegraph/forest; the only context a write lane got was raw file bytes. Three
measured hallucinations (daedalus.linting for daedalus.gui.lint, ShiftManager
for Shift, daedalus.wiki_vault for daedalus.wiki.vault) would each have been
prevented by this brief. These tests build a small synthetic repo rather than
depending on the state of the real one, so they stay meaningful as the repo
changes -- and one test cross-checks against the real repo's own measured
regression (the .captures / build/lib artefact leak caught while building
this module).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daedalus.lanes.graph_brief import (
    ARTEFACT_ROOTS,
    file_symbols,
    graph_brief,
    render_brief,
)


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class FileSymbolsTests(unittest.TestCase):
    def test_functions_and_classes_with_signatures(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "m.py",
                      "def add(a, b):\n    return a + b\n\n\n"
                      "class Shift:\n    def remaining(self):\n        pass\n")
            syms = file_symbols(p)
        self.assertIn("def add(a, b)", syms)
        self.assertIn("class Shift", syms)
        self.assertIn("    def remaining(self)", syms)

    def test_private_excluded_when_asked(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "m.py", "def _hidden():\n    pass\ndef public():\n    pass\n")
            all_syms = file_symbols(p, include_private=True)
            pub_syms = file_symbols(p, include_private=False)
        self.assertIn("def _hidden()", all_syms)
        self.assertNotIn("def _hidden()", pub_syms)
        self.assertIn("def public()", pub_syms)

    def test_dunder_init_kept_other_dunders_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "m.py",
                      "class C:\n    def __init__(self):\n        pass\n"
                      "    def __repr__(self):\n        pass\n")
            syms = file_symbols(p)
        self.assertIn("    def __init__(self)", syms)
        self.assertNotIn("    def __repr__(self)", syms)

    def test_unparsable_file_yields_no_symbols(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(Path(d), "m.py", "def broken(:\n")
            self.assertEqual(file_symbols(p), [])

    def test_missing_file_yields_no_symbols(self):
        self.assertEqual(file_symbols(Path("does/not/exist.py")), [])


class GraphBriefTests(unittest.TestCase):
    def _repo(self, d):
        root = Path(d)
        _write(root, "pkg/shift.py",
              "class Shift:\n    def remaining(self):\n        pass\n")
        _write(root, "pkg/shift_hook.py", "from .shift import Shift\n\n\ndef main():\n    pass\n")
        _write(root, "pkg/unrelated.py", "def noop():\n    pass\n")
        return root

    def test_target_symbols_present(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            brief = graph_brief(root, ["pkg/shift.py"], hops=1)
        self.assertIn("class Shift", brief.text)
        self.assertIn("def remaining(self)", brief.text)

    def test_neighbour_found_via_import_edge(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            brief = graph_brief(root, ["pkg/shift.py"], hops=1)
        self.assertIn("pkg/shift_hook.py", brief.neighbours)
        self.assertNotIn("pkg/unrelated.py", brief.neighbours)

    def test_never_raises_on_missing_repo(self):
        # A brief is context, not a gate: it must degrade to "nothing to say"
        # rather than take a write lane down with it.
        brief = graph_brief("Z:/does/not/exist", ["a.py"], hops=1)
        self.assertIsInstance(brief.text, str)

    def test_render_brief_is_string_convenience(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            text = render_brief(root, ["pkg/shift.py"])
        self.assertIsInstance(text, str)
        self.assertIn("class Shift", text)

    def test_render_brief_never_raises(self):
        # Degrades to "no facts available" rather than crashing OR fabricating
        # content -- a missing repo must never be silently read as an empty one
        # with nothing to report versus one that legitimately has nothing.
        text = render_brief("Z:/does/not/exist", ["a.py"])
        self.assertIsInstance(text, str)
        self.assertIn("No structural facts available", text)

    def test_budget_truncation_is_reported_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # A file with many symbols, so a tiny budget must drop some.
            body = "".join(f"def fn_{i}():\n    pass\n\n\n" for i in range(200))
            _write(root, "pkg/big.py", body)
            brief = graph_brief(root, ["pkg/big.py"], hops=0, budget_chars=200)
        self.assertTrue(brief.truncated)
        self.assertIn("BUDGET", brief.text)
        self.assertIn("omitted", brief.text)

    def test_header_never_pushes_text_over_budget(self):
        # Regression: the header used to be appended AFTER layers were budgeted,
        # so a brief could overshoot by exactly its own preamble size.
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            brief = graph_brief(root, ["pkg/shift.py"], budget_chars=300)
        self.assertLessEqual(brief.char_count, 300 + 200)  # small slop for the header itself

    def test_artefact_roots_never_appear_as_neighbours(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            for artefact_root in ARTEFACT_ROOTS:
                _write(root, f"{artefact_root}wrecked/shift.py",
                      "class Shift:\n    def fake(self):\n        pass\n")
            brief = graph_brief(root, ["pkg/shift.py"], hops=2)
        for n in brief.neighbours:
            self.assertFalse(n.startswith(ARTEFACT_ROOTS), n)
        self.assertNotIn("def fake(self)", brief.text)

    def test_documents_layer_uses_reverse_index(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            index = {
                "n_files": 3,
                "import_edges": {},
                "import_edges_reverse": {},
                "document_links_reverse": {"pkg/shift.py": ["docs/shift.md"]},
            }
            brief = graph_brief(root, ["pkg/shift.py"], index=index)
        self.assertIn("docs/shift.md", brief.text)
        self.assertIn("documented by", brief.text)

    def test_documents_layer_omitted_when_index_lacks_it(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            index = {"n_files": 3, "import_edges": {}, "import_edges_reverse": {}}
            brief = graph_brief(root, ["pkg/shift.py"], index=index)
        self.assertNotIn("DOCUMENTS", brief.text)

    def test_deep_edge_marked(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            # A function-body-only import: not in a top-level import statement.
            _write(root, "pkg/deep.py",
                  "def use_shift():\n    from pkg.shift import Shift\n    return Shift()\n")
            index = {
                "n_files": 4,
                "import_edges": {"pkg/deep.py": ["pkg/shift.py"]},
                "import_edges_reverse": {},
            }
            brief = graph_brief(root, ["pkg/deep.py"], index=index, hops=0)
        line = next(l for l in brief.text.splitlines() if l.startswith("pkg/deep.py ->"))
        self.assertIn("pkg/shift.py*", line)

    def test_shallow_edge_not_marked(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._repo(d)
            index = {
                "n_files": 4,
                "import_edges": {"pkg/shift_hook.py": ["pkg/shift.py"]},
                "import_edges_reverse": {},
            }
            brief = graph_brief(root, ["pkg/shift_hook.py"], index=index, hops=0)
        line = next(l for l in brief.text.splitlines() if l.startswith("pkg/shift_hook.py ->"))
        self.assertIn("pkg/shift.py", line)
        self.assertNotIn("pkg/shift.py*", line)


class RealRepoRegressionTests(unittest.TestCase):
    """Cross-checks against THIS repo, not a synthetic one -- the artefact leak
    (runs/eval/deepseek_lab/wrecked/shift.py appearing as a neighbour of the
    real shift.py) was only caught by running the brief against the real tree."""

    def test_shift_py_brief_has_no_artefact_neighbours(self):
        brief = graph_brief(".", ["daedalus/shift.py"], hops=1)
        for n in brief.neighbours:
            self.assertFalse(n.startswith(ARTEFACT_ROOTS), n)
        self.assertNotIn("wrecked", brief.text)


if __name__ == "__main__":
    unittest.main()
