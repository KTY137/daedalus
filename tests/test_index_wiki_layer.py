"""The wiki layer's index wiring: additive, gated, and its own relation.

``markdown.py`` could parse ``[[wikilinks]]`` and ``index.py`` never called
``knowledge_links`` — a parser with no consumer, the same defect ``skills.py``
carried for a thousand lines. These tests pin the wiring AND the three things it
must not do: move an existing edge set, appear without being asked for, or
publish an unresolved name as if it were an edge.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.structcore.index import build_index, wiki_enabled


def _tree(root: Path) -> None:
    (root / "a.md").write_text(
        "# A\n\nSee [[B]] and [[code:m.py]] and [[type:Foo]] and ![[b.md]].\n",
        encoding="utf-8")
    (root / "b.md").write_text("# B\n\nBack to [[A]].\n", encoding="utf-8")
    (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")


class TheGate(unittest.TestCase):
    def test_it_is_off_by_default(self):
        self.assertFalse(wiki_enabled())

    def test_an_explicit_argument_wins_over_the_environment(self):
        self.assertTrue(wiki_enabled(True))
        self.assertFalse(wiki_enabled(False))

    def test_no_wiki_block_appears_unless_asked_for(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _tree(root)
            idx = build_index(str(root), documents=True)
            for key in ("wiki", "wiki_links", "wiki_code_links", "wiki_type_refs"):
                self.assertNotIn(key, idx, f"{key} must not appear when the gate is off")

    def test_the_layer_needs_documents_indexed(self):
        """Wiki edges are between DOCUMENTS. Asking for the layer without the
        document layer is a contradiction, and it resolves to off rather than to
        a half-built block."""
        with TemporaryDirectory() as d:
            root = Path(d)
            _tree(root)
            idx = build_index(str(root), documents=False, wiki=True)
            self.assertNotIn("wiki", idx)


class ItIsAdditive(unittest.TestCase):
    """The one thing this layer may never do is move an edge set that already
    existed. ``knowledge_links`` returns a SUPERSET of ``internal_links``, so
    building ``document_links`` from it would have been the obvious shortcut and
    a silent change to every consumer's ranking."""

    def test_document_links_are_byte_identical_with_the_gate_on(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _tree(root)
            off = build_index(str(root), documents=True)
            on = build_index(str(root), documents=True, wiki=True)
            self.assertEqual(off.get("document_links"), on.get("document_links"))
            self.assertEqual(off.get("document_links_reverse"),
                             on.get("document_links_reverse"))

    def test_the_scope_key_distinguishes_the_two_builds(self):
        """Without this the in-process cache would serve a wiki-less index to a
        caller that asked for one, or the reverse — the 'degrade silently'
        failure the documents flag already had to solve."""
        with TemporaryDirectory() as d:
            root = Path(d)
            _tree(root)
            off = build_index(str(root), documents=True)
            on = build_index(str(root), documents=True, wiki=True)
            self.assertNotEqual(off["scope_key"], on["scope_key"])
            self.assertTrue(on["scope_key"].endswith("+wiki"))

    def test_code_modules_and_import_edges_do_not_move(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _tree(root)
            off = build_index(str(root), documents=True)
            on = build_index(str(root), documents=True, wiki=True)
            self.assertEqual(off.get("import_edges"), on.get("import_edges"))
            self.assertEqual(sorted(off.get("modules") or {}),
                             sorted(on.get("modules") or {}))


class RelationsStayApart(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        _tree(root)
        self.idx = build_index(str(root), documents=True, wiki=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_doc_to_doc_edge_is_resolved(self):
        self.assertIn("b.md", self.idx["wiki_links"].get("a.md", []))

    def test_a_doc_to_code_edge_is_its_own_relation(self):
        """A link to code says something different from a link to a page, and
        merging them would move fan_in for a module because someone wrote prose
        about it."""
        self.assertIn("m.py", self.idx["wiki_code_links"].get("a.md", []))
        self.assertNotIn("m.py", self.idx["wiki_links"].get("a.md", []))

    def test_a_type_reference_is_carried_as_an_unresolved_NAME(self):
        """`[[type:Foo]]` is a name nobody resolved. Publishing it as an edge
        would assert a binding that was never made — and the type layer, which
        owns resolution, is deliberately not consulted here."""
        self.assertEqual(self.idx["wiki_type_refs"].get("a.md"), ["Foo"])
        self.assertGreaterEqual(self.idx["wiki"]["deferred"], 1)
        self.assertIn("UNRESOLVED", self.idx["wiki"]["note"])

    def test_the_totals_are_reported_including_the_refusals(self):
        w = self.idx["wiki"]
        for key in ("documents", "doc_edges", "code_edges", "type_refs",
                    "unresolved", "ambiguous", "deferred"):
            self.assertIn(key, w, f"{key} must be reported, including when zero")


class RefuseToGuess(unittest.TestCase):
    def test_a_link_to_nothing_is_counted_not_invented(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.md").write_text("# A\n\n[[Nowhere At All]]\n", encoding="utf-8")
            idx = build_index(str(root), documents=True, wiki=True)
            self.assertEqual(idx["wiki_links"].get("a.md", []), [])
            self.assertGreaterEqual(idx["wiki"]["unresolved"], 1)

    def test_an_ambiguous_bare_name_produces_no_edge(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "a.md").write_text("# A\n\n[[setup]]\n", encoding="utf-8")
            (root / "one" / "setup.md").write_text("# Setup\n", encoding="utf-8")
            (root / "two" / "setup.md").write_text("# Setup\n", encoding="utf-8")
            idx = build_index(str(root), documents=True, wiki=True)
            self.assertEqual(idx["wiki_links"].get("a.md", []), [],
                             "picking one of two would be a reproducible fabrication")
            self.assertGreaterEqual(idx["wiki"]["ambiguous"], 1)


class Determinism(unittest.TestCase):
    def test_two_builds_agree(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            _tree(root)
            a = build_index(str(root), documents=True, wiki=True)
            b = build_index(str(root), documents=True, wiki=True)
            for key in ("wiki_links", "wiki_code_links", "wiki_type_refs", "wiki"):
                self.assertEqual(a.get(key), b.get(key))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
