"""The wiki's contract.

Two halves matter most. ``VaultPathValidator`` pins the guard Momus named as the
blocker for the write path — ``PUT /api/knowledge/page/<rel>`` would be the first
endpoint in this API whose path parameter must contain ``/``, and therefore the
first traversal surface. ``RefuseToGuess`` pins the rule that a link which cannot
be resolved is COUNTED, never bound to a near-match.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.wiki import links as lk
from daedalus.wiki import vault as vt


class VaultPathValidator(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _refused(self, rel) -> str:
        path, why = vt.vault_rel(self.root, rel)
        self.assertIsNone(path, f"{rel!r} should have been refused")
        self.assertTrue(why)
        return why

    def test_absolute_paths(self):
        self.assertIn("absolute", self._refused("/etc/passwd"))
        self.assertIn("absolute", self._refused("C:/Windows/x.md"))

    def test_traversal_is_caught_before_normalisation(self):
        """`a/../../b.md` normalises to something innocent; the segment check
        must run first or the backstop is the only defence."""
        self.assertIn("'..'", self._refused("../../secret.md"))
        self.assertIn("'..'", self._refused("a/../../b.md"))

    def test_ntfs_alternate_data_stream(self):
        self.assertIn("alternate data stream", self._refused("page.md:$DATA"))

    def test_reserved_device_names(self):
        for name in ("CON.md", "nul.md", "COM1.md", "lpt9.md"):
            self.assertIn("reserved device", self._refused(name))

    def test_trailing_dot_or_space(self):
        self.assertIn("dot or space", self._refused("page.md."))
        self.assertIn("dot or space", self._refused("page.md "))

    def test_only_markdown_is_a_page(self):
        self.assertIn(".md", self._refused("notes.txt"))
        self.assertIn(".md", self._refused("script.py"))

    def test_the_reserved_top_level_name(self):
        """`vault` is reserved so `[[vault:name/page]]` can never collide with a
        real directory — the ambiguity the first design had."""
        self.assertIn("reserved top-level", self._refused("vault/x.md"))

    def test_empty_and_nul(self):
        self.assertIn("empty", self._refused(""))
        self.assertIn("NUL", self._refused("a\x00b.md"))

    def test_a_symlink_anywhere_on_the_chain_is_refused(self):
        target = self.root / "outside"
        target.mkdir()
        (self.root / "docs").mkdir()
        link = self.root / "docs" / "escape"
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):  # pragma: no cover
            self.skipTest("symlinks not permitted on this machine")
        (target / "p.md").write_text("x", encoding="utf-8")
        self.assertIn("symlink", self._refused("docs/escape/p.md"))

    def test_a_legitimate_path_passes(self):
        path, why = vt.vault_rel(self.root, "guide/setup.md")
        self.assertIsNotNone(path)
        self.assertEqual(why, "")

    def test_refusal_never_raises(self):
        for junk in (None, 123, [], "x" * 5000):
            path, why = vt.vault_rel(self.root, junk)   # must not raise
            self.assertIsNone(path)
            self.assertTrue(why)


class Frontmatter(unittest.TestCase):
    def test_scalars_and_lists(self):
        fm, body = vt.parse_frontmatter(
            "---\ntype: spec\nstatus: verified\ntags: [graph, wiki]\n---\n\n# Title\n")
        self.assertEqual(fm["type"], "spec")
        self.assertEqual(fm["tags"], ["graph", "wiki"])
        self.assertTrue(body.startswith("# Title"))

    def test_dashed_lists(self):
        fm, _ = vt.parse_frontmatter("---\ntags:\n  - a\n  - b\n---\nbody\n")
        self.assertEqual(fm["tags"], ["a", "b"])

    def test_an_unterminated_fence_is_body_not_metadata(self):
        text = "---\ntype: spec\nno closing fence\n"
        fm, body = vt.parse_frontmatter(text)
        self.assertEqual(fm, {})
        self.assertEqual(body, text)

    def test_no_frontmatter_leaves_the_body_untouched(self):
        fm, body = vt.parse_frontmatter("# Just a page\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# Just a page\n")


class PageReading(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.vault = vt.Vault("test", self.root, "project")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_title_precedence_frontmatter_then_h1_then_filename(self):
        self._write("a.md", "---\ntitle: Declared\n---\n# Heading\n")
        self._write("b.md", "# From Heading\n")
        self._write("c_page.md", "no heading here\n")
        self.assertEqual(vt.read_page(self.vault, "a.md")[0].title, "Declared")
        self.assertEqual(vt.read_page(self.vault, "b.md")[0].title, "From Heading")
        self.assertEqual(vt.read_page(self.vault, "c_page.md")[0].title, "c page")

    def test_type_defaults_to_note_and_is_not_a_claim(self):
        self._write("x.md", "body\n")
        self.assertEqual(vt.read_page(self.vault, "x.md")[0].page_type, "note")

    def test_non_utf8_is_refused_with_a_reason(self):
        (self.root / "bad.md").write_bytes(b"\xff\xfe\x00not utf8")
        page, why = vt.read_page(self.vault, "bad.md")
        self.assertIsNone(page)
        self.assertIn("UTF-8", why)

    def test_discover_returns_refusals_rather_than_hiding_them(self):
        self._write("ok.md", "# Fine\n")
        (self.root / "bad.md").write_bytes(b"\xff\xfe")
        pages, refused = vt.discover_pages(self.vault)
        self.assertEqual([p.rel for p in pages], ["ok.md"])
        self.assertEqual(len(refused), 1,
                         "'we could not read it' must not look like 'it is not there'")

    def test_the_tree_is_deterministic(self):
        for rel in ("z.md", "a/b.md", "a/a.md"):
            self._write(rel, "# x\n")
        pages, _ = vt.discover_pages(self.vault)
        self.assertEqual(vt.page_tree(pages), vt.page_tree(pages))


class WikilinkForms(unittest.TestCase):
    def test_every_form_is_parsed(self):
        body = ("See [[Type graph]] and [[Invariants#Hubs]] and [[ADR-009|the ADR]].\n"
                "![[diagram.md]]\n"
                "Code: [[code:daedalus/loop.py#run]] Type: [[type:DSSResult]]\n"
                "Cross: [[vault:global/Doctrine]]\n")
        got = {(l.kind, l.target, l.anchor, l.alias, l.embed)
               for l in lk.extract_wikilinks(body)}
        self.assertIn((lk.DOC, "Type graph", "", "", False), got)
        self.assertIn((lk.DOC, "Invariants", "Hubs", "", False), got)
        self.assertIn((lk.DOC, "ADR-009", "", "the ADR", False), got)
        self.assertIn((lk.DOC, "diagram.md", "", "", True), got)
        self.assertIn((lk.CODE, "daedalus/loop.py", "run", "", False), got)
        self.assertIn((lk.TYPE, "DSSResult", "", "", False), got)
        self.assertIn((lk.VAULT, "global/Doctrine", "", "", False), got)

    def test_line_numbers_are_right(self):
        links = lk.extract_wikilinks("one\ntwo [[Target]]\n")
        self.assertEqual(links[0].line, 2)

    def test_extraction_is_deterministic(self):
        body = "[[a]] [[b]] [[code:x.py]]"
        self.assertEqual([l.to_dict() for l in lk.extract_wikilinks(body)],
                         [l.to_dict() for l in lk.extract_wikilinks(body)])


def _page(rel, body, title=None):
    return vt.Page(rel=rel, title=title or Path(rel).stem, vault="v", body=body)


class RefuseToGuess(unittest.TestCase):
    def test_an_unresolved_link_is_counted_not_bound_to_a_near_match(self):
        pages = [_page("a.md", "see [[Type Graf]]"), _page("type-graph.md", "x", "Type Graph")]
        idx = lk.build_index(pages)
        self.assertEqual(idx.counts()["doc_edges"], 0)
        self.assertEqual(len(idx.unresolved), 1)

    def test_an_ambiguous_title_produces_no_edge(self):
        pages = [_page("a.md", "see [[Setup]]"),
                 _page("guide/setup.md", "x", "Setup"),
                 _page("dev/setup.md", "y", "Setup")]
        idx = lk.build_index(pages)
        self.assertEqual(idx.counts()["doc_edges"], 0)
        self.assertEqual(len(idx.ambiguous), 1)
        self.assertEqual(len(idx.ambiguous[0]["candidates"]), 2)

    def test_a_path_link_resolves_exactly(self):
        pages = [_page("a.md", "see [[guide/setup.md]]"), _page("guide/setup.md", "x")]
        idx = lk.build_index(pages)
        self.assertEqual(idx.counts()["doc_edges"], 1)

    def test_a_self_link_is_not_an_edge(self):
        pages = [_page("a.md", "see [[a]]")]
        self.assertEqual(lk.build_index(pages).counts()["doc_edges"], 0)

    def test_a_type_link_is_parsed_and_never_claimed_resolved(self):
        idx = lk.build_index([_page("a.md", "[[type:DSSResult]]")])
        self.assertEqual(len(idx.type_links), 1)
        self.assertFalse(idx.type_links[0]["resolved"])

    def test_a_code_link_without_a_file_set_is_UNCHECKED_not_fine(self):
        idx = lk.build_index([_page("a.md", "[[code:daedalus/gone.py]]")])
        self.assertFalse(idx.code_links[0]["checked"],
                         "with no file set supplied, staleness is unknown, not false")

    def test_a_code_link_is_stale_when_the_file_set_says_so(self):
        idx = lk.build_index([_page("a.md", "[[code:daedalus/gone.py]]")],
                             known_code_paths={"daedalus/loop.py"})
        self.assertTrue(idx.code_links[0]["checked"])
        self.assertTrue(idx.code_links[0]["stale"])


class BacklinksAndMentions(unittest.TestCase):
    def test_backlinks_are_the_reverse_edges(self):
        pages = [_page("a.md", "[[b]]"), _page("b.md", "nothing")]
        idx = lk.build_index(pages)
        self.assertEqual([r["from"] for r in lk.backlinks(idx, "b.md")], ["a.md"])

    def test_unlinked_mentions_exclude_pages_that_already_link(self):
        target = _page("graph.md", "x", "Type Graph")
        pages = [target, _page("a.md", "see [[Type Graph]]"),
                 _page("b.md", "the Type Graph is mentioned here")]
        idx = lk.build_index(pages)
        got = {m["from"] for m in lk.unlinked_mentions(pages, target, idx)}
        self.assertEqual(got, {"b.md"}, "a.md already links, so it is not an unlinked mention")

    def test_a_very_short_title_yields_no_mentions(self):
        target = _page("a.md", "x", "AI")
        self.assertEqual(lk.unlinked_mentions([target, _page("b.md", "AI is here")],
                                              target, lk.build_index([target])), [])

    def test_mentions_are_bounded(self):
        target = _page("t.md", "x", "Widget")
        pages = [target] + [_page(f"p{i}.md", "the Widget appears") for i in range(40)]
        got = lk.unlinked_mentions(pages, target, lk.build_index(pages), limit=5)
        self.assertEqual(len(got), 5)


class LocalGraph(unittest.TestCase):
    def _chain(self):
        return [_page("a.md", "[[b]]"), _page("b.md", "[[c]]"),
                _page("c.md", "[[d]]"), _page("d.md", "end")]

    def test_depth_one_is_the_immediate_neighbourhood(self):
        idx = lk.build_index(self._chain())
        g = lk.local_graph(idx, "b.md", depth=1)
        self.assertEqual(set(g["nodes"]), {"a.md", "b.md", "c.md"})

    def test_depth_two_reaches_further(self):
        idx = lk.build_index(self._chain())
        g = lk.local_graph(idx, "b.md", depth=2)
        self.assertIn("d.md", g["nodes"])

    def test_it_says_when_it_stopped(self):
        idx = lk.build_index(self._chain())
        g = lk.local_graph(idx, "a.md", depth=3, max_nodes=2)
        self.assertTrue(g["truncated"])
        self.assertTrue(g["note"], "a clipped neighbourhood must not read as complete")

    def test_the_walk_is_deterministic(self):
        idx = lk.build_index(self._chain())
        self.assertEqual(lk.local_graph(idx, "b.md", depth=2),
                         lk.local_graph(idx, "b.md", depth=2))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
