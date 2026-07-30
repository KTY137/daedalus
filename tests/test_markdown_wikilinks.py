"""Obsidian-Flavored-Markdown wikilinks in ``structcore.markdown`` (phase K1).

WHAT THESE TESTS DEFEND, in the order the failures cost something:

  1. NO REGRESSION. A document without a single ``[[`` must parse EXACTLY as it
     did before this module learned wiki syntax. The pin is a fingerprint over
     every field that reaches a consumer -- section boundaries, link tuples,
     external-link list, skeleton text and skeleton receipt -- and the two
     constants below were computed by RUNNING the pre-change module, not by
     copying the post-change output. A fingerprint captured after the fact
     proves nothing.
  2. REFUSE TO GUESS. The module's own docstring says an unresolved link is
     dropped and COUNTED, never bound to a near-match. Wiki syntax adds a second
     way to be wrong -- a bare ``[[note]]`` matching two files -- and the answer
     is the same: no edge, counted as ambiguous. A test that only checked
     "produces some edge" would pass on a parser that guesses.
  3. SEPARATE RELATIONS. ``[[code:x.py]]`` is a doc->code claim, not a doc->doc
     one, and ``[[type:X]]`` is a claim this module deliberately does not
     resolve. Both are pinned as distinct outputs so a later merge into one bag
     of edges has to break a test to happen.
  4. DETERMINISM. The resolution answer must not depend on set iteration order;
     two processes must agree, including on which links they refused.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from daedalus.structcore import markdown as md                     # noqa: E402


# --------------------------------------------------------------------------- #
# 1. BYTE IDENTITY — a document with no wikilinks must not move                 #
# --------------------------------------------------------------------------- #
# Deliberately loaded with every standard form the parser already handled:
# front matter, ATX + setext headings, an inline link, an image, an autolink, a
# mailto, an inline-code false positive, a fenced block containing a link and a
# '#' that is not a heading, a root-relative link, an in-page anchor, a query
# string, and a reference definition.
PLAIN_DOC = """\
---
title: Plain
updated: 2026-07-29
---

# Architecture

Intro prose with a [link](../daedalus/loop.py) and an ![image](img.png).

See <https://example.com/spec> and [mail](mailto:a@b.c).

Setext Heading
--------------

Body with `[inline](code.md)` which is not a link.

```python
# not a heading
see [nope](nope.md)
```

### Lanes

Lane prose, [root](/docs/root.md), [anchor](#lanes), [q](other.md?x=1#top).

[ref]: ../README.md
"""

PLAIN_NO_HEADINGS = """\
Just prose, one [link](../README.md), nothing else.

More prose on a second line.
"""

# Computed by running the module BEFORE wikilink support existed. If either
# constant has to change, a no-wikilink document parses differently than it did,
# which is precisely the regression this file exists to catch -- re-deriving the
# constant from the new code would delete the test while leaving it green.
PLAIN_DOC_FINGERPRINT = "c0ecf5ae88825321b2fb32629aed75de071c2e84078356e0c490e394bfeeadfb"
PLAIN_NO_HEADINGS_FINGERPRINT = "7b9404cc4bf4f5f98b9a552524cb4710f0ea9100201ee08214f2a25e371e215e"

PLAIN_KNOWN = {"README.md", "docs/root.md", "docs/notes/other.md", "daedalus/loop.py"}


def _fingerprint(document: str, text: str) -> str:
    """Hash every parse output a consumer can observe.

    The five DocLink fields hashed are the five that existed before wiki
    support; the new fields are excluded on purpose, because their presence
    with default values is exactly what "the old contract still holds" means.
    """
    parse = md.parse_document(document, text)
    skel = md.document_skeleton(document, text, parse=parse)
    parts = [document, parse.title, str(parse.loc), str(parse.n_chars),
             str(parse.max_depth), str(len(parse.headings))]
    for s in parse.sections:
        parts.append("\x1f".join([
            s.module, s.name, str(s.line), str(s.end_line), str(s.loc),
            s.source, str(s.level), s.anchor, "\x1e".join(s.path), s.language]))
    for l in parse.links:
        parts.append("\x1f".join([l.href, str(l.line), l.kind, l.path, l.anchor]))
    parts.append("\x1e".join(parse.external_links))
    parts.append(skel.text)
    parts.append(repr(sorted(skel.to_dict().items())))
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


class NoWikilinkDocumentIsUnmoved(unittest.TestCase):
    def test_rich_document_parses_byte_identically_to_before(self):
        """GUARD (``_link_occurrences`` / ``_content_lines``). The wiki scanner
        shares the fence and inline-code walk with the standard scanner; a
        refactor that shifted a line index, dropped a reference definition or
        reordered the links on one line would move this hash."""
        self.assertEqual(
            _fingerprint("docs/notes/plain.md", PLAIN_DOC), PLAIN_DOC_FINGERPRINT)

    def test_headless_document_parses_byte_identically_to_before(self):
        """The skeleton's headless-excerpt rung is a separate code path from the
        heading-tree rung, so it gets its own pin."""
        self.assertEqual(
            _fingerprint("docs/notes/plain.md", PLAIN_NO_HEADINGS),
            PLAIN_NO_HEADINGS_FINGERPRINT)

    def test_legacy_edge_set_is_unchanged(self):
        """``index.py`` builds ``document_links`` from ``internal_links``. Its
        answer for a document with no wikilinks must be the old answer."""
        parse = md.parse_document("docs/notes/plain.md", PLAIN_DOC)
        self.assertEqual(md.internal_links(parse, PLAIN_KNOWN),
                         (["docs/notes/other.md", "docs/root.md"], 2))
        self.assertEqual(parse.wiki_links, ())
        self.assertEqual(parse.embeds, ())

    def test_knowledge_view_of_a_plain_document_adds_nothing(self):
        """The new aggregate must reduce to the old one when no wiki syntax is
        present -- otherwise "additive" is a claim, not a fact."""
        parse = md.parse_document("docs/notes/plain.md", PLAIN_DOC)
        std_targets, std_unresolved = md.internal_links(parse, PLAIN_KNOWN)
        k = md.knowledge_links(parse, PLAIN_KNOWN)
        self.assertEqual(list(k.doc_targets), std_targets)
        self.assertEqual(k.unresolved, std_unresolved)
        self.assertEqual((k.code_targets, k.type_refs, k.embed_targets), ((), (), ()))
        self.assertEqual((k.ambiguous, k.deferred, k.n_wikilinks, k.n_embeds),
                         (0, 0, 0, 0))


# --------------------------------------------------------------------------- #
# 2. THE SYNTAX FORMS                                                           #
# --------------------------------------------------------------------------- #
VAULT = {
    "docs/wiki/Index.md",
    "docs/wiki/Alpha.md",
    "docs/wiki/Beta.md",
    "docs/wiki/sub/Gamma.md",
    "docs/wiki/a/dup.md",
    "docs/wiki/b/dup.md",
    "docs/wiki/assets/chart.png",
    "sub/Gamma.md",
    "daedalus/loop.py",
}
DOC = "docs/wiki/Index.md"


def _parse(text: str, document: str = DOC):
    return md.parse_document(document, text)


def _links(text: str, document: str = DOC):
    return _parse(text, document).wiki_links


class WikilinkForms(unittest.TestCase):
    def test_bare_note(self):
        (link,) = _links("See [[Alpha]] for the rest.\n")
        self.assertEqual((link.kind, link.path, link.anchor, link.alias, link.embed),
                         ("wiki", "Alpha", "", "", False))
        self.assertEqual(link.line, 1)

    def test_note_with_heading(self):
        (link,) = _links("See [[Alpha#Router Lanes]].\n")
        self.assertEqual((link.kind, link.path, link.anchor),
                         ("wiki", "Alpha", "Router Lanes"))

    def test_note_with_alias_keeps_the_alias_out_of_the_target(self):
        """GUARD (``_classify_wiki``'s alias partition). An alias is display
        text; folding it into the target would look for a file named
        ``Alpha|the alpha page``, which cannot exist on NTFS -- a link that can
        only ever be unresolved."""
        (link,) = _links("See [[Alpha|the alpha page]].\n")
        self.assertEqual((link.path, link.alias), ("Alpha", "the alpha page"))

    def test_note_with_heading_and_alias(self):
        (link,) = _links("See [[Alpha#Lanes|lanes]].\n")
        self.assertEqual((link.path, link.anchor, link.alias),
                         ("Alpha", "Lanes", "lanes"))

    def test_embed_is_distinguished_from_a_link(self):
        """GUARD (``embed``). A transclusion renders the target's body inline; a
        link does not. A caller that cannot tell them apart either inlines every
        link or inlines nothing."""
        plain, embed_note, embed_asset = _links(
            "[[Alpha]]\n\n![[Beta]]\n\n![[chart.png]]\n")
        self.assertFalse(plain.embed)
        self.assertTrue(embed_note.embed)
        self.assertTrue(embed_asset.embed)
        self.assertEqual([l.line for l in (plain, embed_note, embed_asset)], [1, 3, 5])

    def test_code_link_is_a_separate_relation(self):
        (link,) = _links("Implemented in [[code:daedalus/loop.py]].\n")
        self.assertEqual((link.kind, link.namespace, link.path),
                         ("code", "code", "daedalus/loop.py"))

    def test_code_link_carries_the_symbol(self):
        (link,) = _links("See [[code:daedalus/loop.py#run|the loop]].\n")
        self.assertEqual((link.kind, link.path, link.anchor, link.alias),
                         ("code", "daedalus/loop.py", "run", "the loop"))

    def test_type_link_is_parsed_and_carried_but_never_resolved(self):
        """GUARD (the ``type`` branch). The type layer is a parallel build; this
        module must not import it and must not pretend to answer for it."""
        (link,) = _links("Returns a [[type:DSSResult]].\n")
        self.assertEqual((link.kind, link.namespace, link.path),
                         ("type", "type", "DSSResult"))
        parse = _parse("Returns a [[type:DSSResult]].\n")
        resolved = md.resolve_wiki_links(parse, VAULT)
        self.assertEqual([status for _, _, status in resolved], [md.WIKI_DEFERRED])
        self.assertEqual([target for _, target, _ in resolved], [None])

    def test_in_document_anchor_is_not_an_edge(self):
        (link,) = _parse("Jump to [[#Lanes]].\n").links
        self.assertEqual((link.kind, link.path, link.anchor), ("anchor", "", "Lanes"))

    def test_off_repo_url_in_brackets_stays_an_attribute(self):
        """GUARD (``_classify_wiki``'s scheme test). An edge asserts a relation
        between two nodes in this forest; a URL has no second node. The rule
        does not bend because the author used wiki brackets."""
        parse = _parse("See [[https://example.com/x|the spec]].\n")
        (link,) = parse.links
        self.assertEqual(link.kind, "external")
        self.assertEqual(parse.external_links, ("https://example.com/x",))
        self.assertEqual(md.knowledge_links(parse, VAULT).doc_targets, ())

    def test_wikilink_in_a_fence_or_in_backticks_is_not_a_link(self):
        """GUARD (``_content_lines``). This repo's own documentation quotes wiki
        syntax; indexing those quotations would fabricate edges out of prose
        that is teaching the syntax."""
        text = (
            "Real: [[Alpha]]\n"
            "\n"
            "Inline `[[Beta]]` is a rendering.\n"
            "\n"
            "```markdown\n"
            "[[Beta]]\n"
            "![[chart.png]]\n"
            "```\n"
        )
        self.assertEqual([l.path for l in _links(text)], ["Alpha"])

    def test_unterminated_or_nested_brackets_are_not_links(self):
        text = "[[Alpha\n]] and [[ ]] and [[]]\n"
        self.assertEqual(_links(text), ())

    def test_standard_links_still_parse_in_a_document_that_has_wikilinks(self):
        """The two syntaxes are disjoint; neither scanner may eat the other's
        matches, or a mixed document silently loses half its edges."""
        parse = _parse("A [link](Alpha.md) and a [[Beta]].\n")
        self.assertEqual([(l.kind, l.path) for l in parse.links],
                         [("path", "Alpha.md"), ("wiki", "Beta")])


# --------------------------------------------------------------------------- #
# 3. RESOLUTION — and the four ways it refuses                                  #
# --------------------------------------------------------------------------- #
class Resolution(unittest.TestCase):
    def test_bare_name_resolves_to_the_single_matching_file(self):
        k = md.knowledge_links(_parse("[[Alpha]]\n"), VAULT)
        self.assertEqual(k.doc_targets, ("docs/wiki/Alpha.md",))
        self.assertEqual((k.unresolved, k.ambiguous, k.deferred), (0, 0, 0))

    def test_embed_of_an_asset_resolves_to_the_asset(self):
        k = md.knowledge_links(_parse("![[chart.png]]\n"), VAULT)
        self.assertEqual(k.doc_targets, ("docs/wiki/assets/chart.png",))
        self.assertEqual(k.embed_targets, ("docs/wiki/assets/chart.png",))
        self.assertEqual(k.n_embeds, 1)

    def test_the_md_extension_is_a_second_round_not_a_first_guess(self):
        """GUARD (``resolve_wiki_target``'s form ladder). If ``.md`` were
        appended first, ``![[chart.png]]`` would hunt for ``chart.png.md``,
        find nothing, and the image would be reported unresolved."""
        lookup = md.wiki_lookup(VAULT)
        self.assertEqual(
            md.resolve_wiki_target(DOC, "chart.png", lookup, default_ext=".md"),
            ("docs/wiki/assets/chart.png", md.WIKI_RESOLVED))
        self.assertEqual(
            md.resolve_wiki_target(DOC, "Alpha", lookup, default_ext=".md"),
            ("docs/wiki/Alpha.md", md.WIKI_RESOLVED))

    def test_code_link_resolves_against_the_code_file_set(self):
        k = md.knowledge_links(_parse("[[code:daedalus/loop.py#run]]\n"), VAULT)
        self.assertEqual(k.code_targets, ("daedalus/loop.py",))
        self.assertEqual(k.doc_targets, ())

    def test_code_targets_never_leak_into_doc_targets(self):
        """GUARD (``knowledge_links``' bucket split). doc->code and doc->doc are
        different claims; only one of them has a staleness question."""
        k = md.knowledge_links(_parse("[[Alpha]] and [[code:daedalus/loop.py]]\n"), VAULT)
        self.assertEqual(k.doc_targets, ("docs/wiki/Alpha.md",))
        self.assertEqual(k.code_targets, ("daedalus/loop.py",))

    def test_self_link_is_not_an_edge_and_is_not_unresolved(self):
        k = md.knowledge_links(_parse("[[Index]]\n"), VAULT)
        self.assertEqual(k.doc_targets, ())
        self.assertEqual((k.unresolved, k.ambiguous), (0, 0))

    def test_unresolved_wikilink_is_dropped_and_counted(self):
        """The module's oldest rule, applied to the new syntax."""
        k = md.knowledge_links(_parse("[[Missing]] and ![[missing.png]]\n"), VAULT)
        self.assertEqual(k.doc_targets, ())
        self.assertEqual(k.unresolved, 2)
        self.assertEqual(k.ambiguous, 0)

    def test_unresolved_code_link_is_dropped_and_counted(self):
        k = md.knowledge_links(_parse("[[code:daedalus/gone.py#run]]\n"), VAULT)
        self.assertEqual(k.code_targets, ())
        self.assertEqual(k.unresolved, 1)

    def test_ambiguous_bare_name_emits_no_link_and_counts(self):
        """GUARD (``resolve_wiki_target``'s tie check). Two files named
        ``dup.md``: taking the first sorted candidate would be DETERMINISTIC and
        still fabricated -- the same wrong edge on every run, with a receipt."""
        parse = _parse("[[dup]]\n")
        k = md.knowledge_links(parse, VAULT)
        self.assertEqual(k.doc_targets, ())
        self.assertEqual((k.ambiguous, k.unresolved), (1, 0))
        (_, target, status) = md.resolve_wiki_links(parse, VAULT)[0]
        self.assertIsNone(target)
        self.assertEqual(status, md.WIKI_AMBIGUOUS)

    def test_ambiguous_path_reading_emits_no_link_and_counts(self):
        """``[[sub/Gamma]]`` from ``docs/wiki/Index.md`` is readable as
        vault-root-relative (``sub/Gamma.md``) or document-relative
        (``docs/wiki/sub/Gamma.md``). Both exist here. Picking one is the exact
        failure mode the plan's B-M2 names: unresolved would be honest, resolved
        to one of two is fabrication."""
        k = md.knowledge_links(_parse("[[sub/Gamma]]\n"), VAULT)
        self.assertEqual(k.doc_targets, ())
        self.assertEqual(k.ambiguous, 1)

    def test_an_unambiguous_path_still_resolves(self):
        """The tie rule must not swallow the ordinary case: with only one
        reading present in the file set, the link binds."""
        vault = set(VAULT) - {"sub/Gamma.md"}
        k = md.knowledge_links(_parse("[[sub/Gamma]]\n"), vault)
        self.assertEqual(k.doc_targets, ("docs/wiki/sub/Gamma.md",))
        self.assertEqual(k.ambiguous, 0)

    def test_type_reference_is_counted_as_deferred_never_unresolved(self):
        """"We did not look" and "we looked and found nothing" are different
        claims. Folding type refs into ``unresolved`` would report a defect in
        the document where the truth is a missing layer in the parser."""
        k = md.knowledge_links(_parse("[[type:DSSResult]] and [[type:CodeUnit]]\n"), VAULT)
        self.assertEqual(k.type_refs, ("CodeUnit", "DSSResult"))
        self.assertEqual((k.deferred, k.unresolved, k.ambiguous), (2, 0, 0))
        self.assertEqual(k.doc_targets, ())

    def test_vault_prefix_is_deferred_and_never_binds_a_local_file(self):
        """GUARD (the ``vault`` branch). Cross-vault links are phase K6, gated on
        a security review. Without this branch ``[[vault:global/Alpha]]`` would
        fall through to the note matcher; the danger is not that it fails, it is
        that a same-named local file makes it succeed."""
        parse = _parse("[[vault:global/Alpha]]\n")
        (link,) = parse.wiki_links
        self.assertEqual((link.kind, link.namespace), ("deferred", "vault"))
        k = md.knowledge_links(parse, VAULT)
        self.assertEqual((k.doc_targets, k.code_targets), ((), ()))
        self.assertEqual((k.deferred, k.unresolved, k.ambiguous), (1, 0, 0))

    def test_a_namespace_is_a_fixed_literal_not_a_family_of_spellings(self):
        """``[[Code:x]]`` is not the namespace -- accepting case variants would
        be guessing at intent. It falls through to the same scheme test standard
        links use, so it is carried as an attribute and produces NO edge, which
        is the conservative outcome for syntax nobody defined."""
        parse = _parse("[[Code:daedalus/loop.py]]\n")
        (link,) = parse.links
        self.assertEqual((link.kind, link.namespace), ("external", ""))
        k = md.knowledge_links(parse, VAULT)
        self.assertEqual((k.doc_targets, k.code_targets), ((), ()))

    def test_wikilinks_do_not_silently_enter_the_legacy_edge_set(self):
        """``internal_links`` is what ``index.py`` consumes today. Wiki edges
        arrive through ``knowledge_links``, so wiring them is a decision
        somebody makes, not a side effect of this change."""
        parse = _parse("[[Alpha]] and [[code:daedalus/loop.py]]\n")
        self.assertEqual(md.internal_links(parse, VAULT), ([], 0))


# --------------------------------------------------------------------------- #
# 4. DETERMINISM — two processes, byte-identical answers                        #
# --------------------------------------------------------------------------- #
MIXED = """\
# Index

Links: [[Alpha]], [[Beta|b]], [[sub/Gamma]], [[dup]], [[Missing]].

Code: [[code:daedalus/loop.py#run]]. Type: [[type:DSSResult]].

Vault: [[vault:global/Alpha]]. Embeds: ![[Beta]] ![[chart.png]].

Standard: [loop](../../daedalus/loop.py) and <https://example.com>.
"""


class Determinism(unittest.TestCase):
    def test_answer_does_not_depend_on_file_set_iteration_order(self):
        """GUARD (``wiki_lookup``'s sort). The ambiguity verdict is a function
        of a candidate SET; if the set were iterated unsorted, which candidate
        won -- and therefore whether an edge existed at all -- would vary
        between processes for the same input."""
        parse = _parse(MIXED)
        orders = [
            sorted(VAULT),
            sorted(VAULT, reverse=True),
            list(VAULT),
            {f: 0 for f in sorted(VAULT, reverse=True)},
        ]
        answers = {repr(md.knowledge_links(parse, o).to_dict()) for o in orders}
        self.assertEqual(len(answers), 1, answers)

    def test_repeated_parses_are_identical(self):
        first = md.knowledge_links(_parse(MIXED), VAULT)
        second = md.knowledge_links(_parse(MIXED), VAULT)
        self.assertEqual(first, second)

    def test_the_mixed_document_totals_are_exact(self):
        """One document, every form at once, every count nailed down -- so a
        future change that quietly reclassifies one form has to move a number
        here rather than sliding through the per-form tests."""
        k = md.knowledge_links(_parse(MIXED), VAULT)
        # ``daedalus/loop.py`` is here from the STANDARD link ``[loop](...)`` --
        # standard links keep landing where they always did. The wikilink
        # ``[[code:daedalus/loop.py]]`` is the entry in ``code_targets``.
        self.assertEqual(k.doc_targets, ("daedalus/loop.py", "docs/wiki/Alpha.md",
                                         "docs/wiki/Beta.md",
                                         "docs/wiki/assets/chart.png"))
        self.assertEqual(k.code_targets, ("daedalus/loop.py",))
        self.assertEqual(k.embed_targets, ("docs/wiki/Beta.md",
                                           "docs/wiki/assets/chart.png"))
        self.assertEqual(k.type_refs, ("DSSResult",))
        self.assertEqual(k.unresolved, 1)      # [[Missing]]
        self.assertEqual(k.ambiguous, 2)       # [[sub/Gamma]], [[dup]]
        self.assertEqual(k.deferred, 2)        # [[type:...]], [[vault:...]]
        self.assertEqual(k.external, 1)
        self.assertEqual(k.n_wikilinks, 10)
        self.assertEqual(k.n_embeds, 2)


if __name__ == "__main__":                                        # pragma: no cover
    unittest.main()
