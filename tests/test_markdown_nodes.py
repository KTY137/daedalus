"""Markdown as a StructCore node kind.

WHAT THIS FILE IS DEFENDING, in the order the failures actually cost something:

  1. THE DEFECT. ``structcore`` indexed 285 files of this repo and ZERO
     markdown. A context plan for a task specified entirely in a 3592-line
     markdown architecture document selected three TypeScript files, because the
     specification was not a node the selector could see. Documents must be
     indexable AND selectable; either alone fixes nothing.
  2. EGRESS. A new node kind must not become a way to ship bytes that code
     could not. Same gate, same lane semantics, same fail-closed refusal.
  3. HONESTY. A "distilled" view larger than its own source is a lie, and this
     repo already pinned that for code
     (``test_room_wiring::test_no_file_is_ever_inlined_larger_than_its_own_body``).
     The document analogue must hold too, and must SAY what it dropped.
  4. NO COLLATERAL. Documents are not code. They must stay out of the clone
     passes, the hotspot ranking, the import graph, the safety fence's
     denominator and the temporal-coupling report -- and the default index must
     be unchanged, because turning documents on moves ``total_tokens`` and
     therefore every published ``reduction_pct``.

EVERY GUARD BELOW IS RED-VERIFIED. 27 guards were disabled one at a time (by
single-line source substitution, restored immediately after) and the named test
was confirmed to FAIL in each case -- 36 test failures across the 27 runs, and
0 guards whose test stayed green. A guard whose test still passes when the guard
is gone is not a guard, and two of these tests only became real guards because
that check caught them passing regardless: the call-graph one needed a heading
title to also appear as a word in another section's prose, and the clone one
needed the two fixture documents to end with a byte-identical section. Each such
test names the guard it defends in its own docstring, so re-running the check by
hand is a matter of breaking the named line.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from daedalus import sensitivity                                   # noqa: E402
from daedalus.structcore import graph as graph_mod                 # noqa: E402
from daedalus.structcore import markdown as md                     # noqa: E402
from daedalus.structcore.churn import temporal_misses              # noqa: E402
from daedalus.structcore.dss import (FILE_NODE_KINDS,              # noqa: E402
                                     build_forest_hierarchy,
                                     semantic_super_sample)
from daedalus.structcore.forest import build_knowledge_forest      # noqa: E402
from daedalus.structcore.index import (build_index, cached_index,  # noqa: E402
                                       documents_enabled)
from daedalus.structcore.languages import doc_spec_for, spec_for   # noqa: E402
from daedalus.structcore.slice import semantic_slice               # noqa: E402


# A credential that is ASSEMBLED, never written as a literal. Writing a real
# AWS-shaped key into this file would make the file itself trip the floor it is
# testing, and every slice of the test suite would then be withheld for a
# reason that has nothing to do with the code under test.
AWS_KEY = "AKIA" + "Q7XM3PL9ZR2VB4KD"          # matches SECRET_FLOOR_CONTENT
PLAIN_SECRET_LINE = 'password = "' + "hunter2-not-a-real-one" + '"'


def _mkrepo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="md-nodes-"))
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# 1. HIERARCHY — heading levels are a real tree                                 #
# --------------------------------------------------------------------------- #
DOC = """
# Architecture

Intro prose that is not a heading.

## Router

Router prose.

### Lanes

Lane prose.

### Gates

Gate prose.

## Storage

Storage prose.
"""


class HeadingTree(unittest.TestCase):
    def setUp(self):
        self.parse = md.parse_document("docs/arch.md", textwrap.dedent(DOC).lstrip("\n"))

    def test_levels_and_ancestry_form_a_tree(self):
        """H1 -> H2 -> H3 is the analogue of module -> class -> function, so the
        ancestry has to be recorded, not just the level number."""
        by_name = {s.name: s for s in self.parse.sections}
        self.assertEqual(by_name["Architecture"].level, 1)
        self.assertEqual(by_name["Architecture"].path, ())
        self.assertEqual(by_name["Router"].level, 2)
        self.assertEqual(by_name["Router"].path, ("Architecture",))
        self.assertEqual(by_name["Lanes"].level, 3)
        self.assertEqual(by_name["Lanes"].path, ("Architecture", "Router"))
        # A sibling H3 does not become a child of the previous H3.
        self.assertEqual(by_name["Gates"].path, ("Architecture", "Router"))
        # Descending back to H2 pops the H3 off the stack.
        self.assertEqual(by_name["Storage"].path, ("Architecture",))
        self.assertEqual(self.parse.max_depth, 3)

    def test_a_section_runs_to_the_next_heading_of_equal_or_higher_level(self):
        """The unit boundary. An H2 CONTAINS its H3s -- exactly as a Python
        function's source contains its nested defs (``parse._units_from_tree``
        emits both) -- and ends at the next H2, not at the next heading."""
        by_name = {s.name: s for s in self.parse.sections}
        router = by_name["Router"]
        self.assertIn("### Lanes", router.source)
        self.assertIn("### Gates", router.source)
        self.assertNotIn("## Storage", router.source)
        lanes = by_name["Lanes"]
        self.assertIn("Lane prose.", lanes.source)
        self.assertNotIn("Gate prose.", lanes.source)

    def test_a_document_with_no_headings_still_has_one_unit(self):
        """Zero units would say "this file has no content", which is false. The
        preamble is the analogue of module-level code."""
        parse = md.parse_document("notes.md", "just prose\nand more prose\n")
        self.assertEqual(len(parse.sections), 1)
        self.assertEqual(parse.sections[0].level, 0)
        self.assertEqual(parse.sections[0].name, "(preamble)")

    def test_a_hash_inside_a_fenced_code_block_is_not_a_heading(self):
        """GUARD (fence tracking in ``markdown._headings``). Without it every
        Python/shell comment in every code sample becomes an H1, and the
        "heading tree" is mostly source comments."""
        text = (
            "# Real\n\n"
            "```python\n"
            "# not a heading\n"
            "## also not a heading\n"
            "```\n\n"
            "## Also real\n"
        )
        names = [s.name for s in md.parse_document("d.md", text).headings]
        self.assertEqual(names, ["Real", "Also real"])

    def test_atx_requires_whitespace_after_the_hashes(self):
        """``#hashtag`` and ``#!/bin/sh`` are not headings. Fabricated structure
        is worse than missing structure."""
        text = "#hashtag\n#!/bin/sh\n# Real Heading\n"
        names = [s.name for s in md.parse_document("d.md", text).headings]
        self.assertEqual(names, ["Real Heading"])

    def test_front_matter_is_not_content(self):
        text = "---\ntitle: x\n---\n\n# Body\n"
        parse = md.parse_document("d.md", text)
        self.assertEqual([s.name for s in parse.headings], ["Body"])
        self.assertEqual(parse.sections[0].name, "Body")   # no fake preamble

    def test_setext_headings_are_recognised_but_a_table_rule_is_not(self):
        text = (
            "Title\n=====\n\nSub\n---\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
            "- item\n---\n"
        )
        heads = md.parse_document("d.md", text).headings
        self.assertEqual([(h.name, h.level) for h in heads],
                         [("Title", 1), ("Sub", 2)])

    def test_duplicate_headings_get_distinct_anchors(self):
        text = "## Notes\n\na\n\n## Notes\n\nb\n"
        anchors = [h.anchor for h in md.parse_document("d.md", text).headings]
        self.assertEqual(anchors, ["notes", "notes-1"])


# --------------------------------------------------------------------------- #
# 2. EDGES — intra-repo links are edges, off-repo URLs are attributes           #
# --------------------------------------------------------------------------- #
LINKY = """
# Spec

See [the parser](../daedalus/parse.py) and [a section](./other.md#the-part).
Reference style: [ref][r1]

[r1]: ./other.md

Off-repo: [anthropic](https://example.com/x) and <https://example.org>
and [mail](mailto:a@b.c) and [self](#spec).

Missing: [gone](./deleted.md)

```
[not a link](./fenced.md)
```
`[nor this](./inline.md)`
"""


class DocumentEdges(unittest.TestCase):
    def setUp(self):
        self.parse = md.parse_document("docs/spec.md",
                                       textwrap.dedent(LINKY).lstrip("\n"))
        self.known = {"daedalus/parse.py", "docs/other.md", "docs/spec.md"}

    def test_intra_repo_links_resolve_to_rel_paths(self):
        targets, unresolved = md.internal_links(self.parse, self.known)
        self.assertEqual(targets, ["daedalus/parse.py", "docs/other.md"])
        self.assertEqual(unresolved, 1)          # ./deleted.md, counted not guessed

    def test_a_fragment_does_not_change_the_target_file(self):
        """``[x](path#anchor)`` is an edge to ``path``. Dropping the fragment is
        what makes the two spellings one edge instead of two nodes."""
        self.assertEqual(
            md.resolve_link("docs/spec.md", "./other.md", self.known),
            "docs/other.md")

    def test_off_repo_urls_are_attributes_not_edges(self):
        """GUARD (``_classify``'s scheme test). An edge asserts a relation
        between two nodes of THIS forest; an https link has no second node, so
        making it an edge would point at nothing."""
        targets, _ = md.internal_links(self.parse, self.known)
        self.assertNotIn("https://example.com/x", targets)
        self.assertTrue(any("example.com" in u for u in self.parse.external_links))
        self.assertTrue(any("mailto:" in u for u in self.parse.external_links))
        self.assertEqual([l for l in self.parse.path_links
                          if l.path.startswith("http")], [])

    def test_a_pure_fragment_is_not_a_file_edge(self):
        self.assertTrue(any(l.kind == "anchor" for l in self.parse.links))
        targets, _ = md.internal_links(self.parse, self.known)
        self.assertNotIn("docs/spec.md", targets)   # self-link is not an edge

    def test_links_inside_code_are_not_links(self):
        hrefs = {l.href for l in self.parse.links}
        self.assertNotIn("./fenced.md", hrefs)
        self.assertNotIn("./inline.md", hrefs)

    def test_an_image_is_not_a_document_edge(self):
        parse = md.parse_document("d.md", "![alt](./pic.png)\n")
        self.assertEqual(parse.path_links, ())

    def test_a_link_escaping_the_repo_root_is_refused(self):
        """GUARD (``resolve_link``'s ``..`` refusal). Outside the root there is
        no node to point at, and binding to a near-match would be a guess."""
        self.assertIsNone(
            md.resolve_link("docs/spec.md", "../../../etc/passwd",
                            {"docs/spec.md"}))

    def test_an_unresolvable_link_is_dropped_and_counted_never_guessed(self):
        parse = md.parse_document("d.md", "[x](./nowhere.md)\n")
        targets, unresolved = md.internal_links(parse, {"d.md", "somewhere.md"})
        self.assertEqual(targets, [])
        self.assertEqual(unresolved, 1)


# --------------------------------------------------------------------------- #
# 3. THE SLICE MUST STAY HONEST                                                 #
# --------------------------------------------------------------------------- #
class HonestDocumentSkeleton(unittest.TestCase):
    def test_a_skeleton_is_never_larger_than_its_own_document(self):
        """THE INVARIANT THE FEATURE RESTS ON, and the one this repo has already
        paid for once in ``room._distill_one``. Checked over every markdown file
        actually in this repo, plus two adversarial shapes:
          * a document that is ALL headings and no prose (the outline cannot be
            cheaper than the text), and
          * a tiny document (the header alone would exceed it).
        """
        cases: list[tuple[str, str]] = []
        for p in sorted(REPO.rglob("*.md")):
            if any(part.startswith(".") or part in {"node_modules", "build", "dist"}
                   for part in p.relative_to(REPO).parts):
                continue
            cases.append((p.relative_to(REPO).as_posix(),
                          p.read_text(encoding="utf-8", errors="replace")))
        cases.append(("all_headings.md", "\n".join(f"{'#' * ((i % 6) + 1)} h{i}"
                                                   for i in range(400))))
        cases.append(("tiny.md", "# a\n"))
        cases.append(("empty.md", ""))
        self.assertGreater(len(cases), 3)
        for rel, text in cases:
            sk = md.document_skeleton(rel, text)
            self.assertLessEqual(
                len(sk.text), len(text),
                f"{rel}: skeleton {len(sk.text)} > raw {len(text)}")

    def test_max_chars_is_respected_as_well(self):
        text = "\n".join(f"## section {i}\n\nbody {i}\n" for i in range(200))
        for cap in (4000, 800, 200, 40):
            sk = md.document_skeleton("d.md", text, max_chars=cap)
            self.assertLessEqual(len(sk.text), cap, f"cap={cap}")

    def test_the_skeleton_says_what_it_dropped(self):
        """Dropping is allowed; dropping SILENTLY is not. A reader must be able
        to tell a distilled document from a short one."""
        text = "# T\n\n" + ("prose line\n" * 500) + "\n## S\n\n" + ("more\n" * 500)
        sk = md.document_skeleton("d.md", text)
        self.assertTrue(sk.distilled)
        self.assertIn("PROSE DROPPED", sk.text)
        self.assertIn("headings kept", sk.text)
        self.assertRegex(sk.text, r"\d+ of \d+ lines")
        self.assertGreater(sk.dropped_chars, 0)
        # the headings themselves survive -- that is the "signature" half
        self.assertIn("# T", sk.text)
        self.assertIn("## S", sk.text)
        self.assertNotIn("prose line", sk.text)

    def test_when_no_skeleton_is_smaller_the_raw_document_is_returned_and_said_so(self):
        text = "# a\n## b\n### c\n"
        sk = md.document_skeleton("d.md", text)
        self.assertFalse(sk.distilled)
        self.assertEqual(sk.degraded, "raw")
        self.assertEqual(sk.text, text)

    def test_a_headingless_document_still_gets_a_bounded_orientation_excerpt(self):
        """A tree-less document has no tree to keep, and a receipt that says
        "0 headings kept" tells the reading model nothing. A bounded, LABELLED
        excerpt is emitted -- never presented as the whole document."""
        text = "\n".join(f"prose line {i}" for i in range(500))
        sk = md.document_skeleton("notes.md", text)
        self.assertTrue(sk.distilled)
        self.assertLessEqual(len(sk.text), len(text))
        self.assertIn("prose line 0", sk.text)
        self.assertNotIn("prose line 400", sk.text)
        self.assertIn("no headings in this document", sk.text)

    def test_the_degrade_ladder_is_deterministic(self):
        text = "\n".join(f"### heading number {i}" for i in range(300))
        a = md.document_skeleton("d.md", text)
        b = md.document_skeleton("d.md", text)
        self.assertEqual(a.text, b.text)
        self.assertEqual(a.degraded, b.degraded)

    def test_a_real_archived_repo_document_distils_hard(self):
        p = REPO / "docs" / "archive" / "2026-07" / "HANDOFF.md"
        if not p.exists():
            self.skipTest("docs/archive/2026-07/HANDOFF.md absent")
        text = p.read_text(encoding="utf-8", errors="replace")
        sk = md.document_skeleton("docs/archive/2026-07/HANDOFF.md", text)
        self.assertTrue(sk.distilled)
        self.assertLess(len(sk.text), len(text) * 0.25)


# --------------------------------------------------------------------------- #
# 4. EGRESS — the riskiest part                                                 #
# --------------------------------------------------------------------------- #
SECRET_DOC = f"""
# Deployment

Here is the production key, pasted into the runbook by mistake:

    aws_access_key_id = {AWS_KEY}

## Notes

More prose.
"""

CLEAN_DOC = """
# Clean

Prose with no credential in it at all.

See [the module](../pkg/mod.py).
"""


class DocumentEgress(unittest.TestCase):
    """A document must not become a way to ship bytes that code could not."""

    @classmethod
    def setUpClass(cls):
        cls.root = _mkrepo({
            "pkg/mod.py": "def helper(x):\n    return x + 1\n",
            "pkg/user.py": "from pkg.mod import helper\n\n\ndef go():\n    return helper(1)\n",
            "docs/clean.md": CLEAN_DOC,
            "docs/leaky.md": SECRET_DOC,
        })
        cls.idx = build_index(cls.root, documents=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_the_secret_floor_sees_a_markdown_file_at_all(self):
        rule = sensitivity.secret_floor_rule(
            "docs/leaky.md", textwrap.dedent(SECRET_DOC))
        self.assertIsNotNone(rule)
        self.assertIn("AWS", rule)

    def test_a_document_is_gated_exactly_as_the_same_bytes_in_code_would_be(self):
        """The crisp statement of the rule: identical bytes must get an
        identical verdict whether the extension is .md or .py, in BOTH lanes.
        If markdown were more permissive, renaming a file would be an egress
        bypass."""
        body = textwrap.dedent(SECRET_DOC)
        for lane in ("trusted", "untrusted"):
            md_rule = sensitivity.slice_egress_rule("docs/leaky.md", body, lane=lane)
            py_rule = sensitivity.slice_egress_rule("docs/leaky.py", body, lane=lane)
            self.assertIsNotNone(md_rule, f"lane={lane}: markdown was not gated")
            self.assertEqual(md_rule, py_rule, f"lane={lane}")

    def test_a_secret_bearing_document_is_refused_as_a_focus_fail_closed(self):
        res = semantic_slice(self.root, "docs/leaky.md", idx=self.idx)
        self.assertNotIn(AWS_KEY, res["slice_text"])
        self.assertEqual(res["withheld_count"], 1)
        self.assertEqual(res["withheld"][0]["file"], "docs/leaky.md")
        self.assertEqual(res["withheld"][0]["role"], "focus")
        self.assertIn("WITHHELD", res["slice_text"])
        self.assertEqual(res["included"], [])

    def test_the_symbol_path_of_a_document_is_gated_too(self):
        """``docs/leaky.md::Notes`` must not slip past the file-level refusal:
        the floor scans the FULL focus text, not the requested section."""
        res = semantic_slice(self.root, "docs/leaky.md::Notes", idx=self.idx)
        self.assertNotIn(AWS_KEY, res["slice_text"])
        self.assertEqual(res["withheld_count"], 1)

    def test_a_secret_bearing_document_is_withheld_as_a_NEIGHBOUR(self):
        """GUARD (``_emit_ok`` before ``_skeleton`` in the document loop). The
        focus refusal is not enough: a document reaches slice_text as a
        neighbour skeleton too, and that path reads the file off disk."""
        root = _mkrepo({
            "pkg/mod.py": "def helper(x):\n    return x + 1\n",
            "docs/leaky.md": SECRET_DOC + "\nSee [mod](../pkg/mod.py).\n",
        })
        try:
            idx = build_index(root, documents=True)
            self.assertIn("docs/leaky.md", idx["document_links"])
            res = semantic_slice(root, "pkg/mod.py", idx=idx)
            self.assertNotIn(AWS_KEY, res["slice_text"])
            self.assertIn("docs/leaky.md",
                          [w["file"] for w in res["withheld"]])
            self.assertIn("WITHHELD", res["slice_text"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_plaintext_credential_line_in_prose_is_also_caught(self):
        rule = sensitivity.secret_floor_rule("docs/x.md", PLAIN_SECRET_LINE)
        self.assertIsNotNone(rule)

    def test_a_clean_document_is_not_withheld(self):
        """Precision matters as much as recall: a floor that withholds ordinary
        documentation makes the feature useless and pushes people to disable it."""
        res = semantic_slice(self.root, "docs/clean.md", idx=self.idx)
        self.assertEqual(res["withheld"], [])
        self.assertIn("Prose with no credential", res["slice_text"])

    def test_FINDING_the_untrusted_lane_allow_list_lets_documents_through(self):
        """CHARACTERIZATION + ROUTED FINDING. Not an endorsement.

        ``sensitivity.GENERIC_ALLOW_SUBSTRINGS`` contains the literal ``".md"``,
        so on the UNTRUSTED lane (an external provider) an ordinary markdown
        document passes the default-deny allow-list while the same prose in a
        ``.py`` file is withheld. That policy predates this feature -- but until
        now it was unreachable for documents, because documents were not indexed
        and so could never enter a slice at all. Turning ``documents=True`` on
        makes it reachable: a design doc, a handoff, or ``runs/council/room.md``
        becomes egressable to an untrusted provider, gated only by the secret
        floor.

        Three notes, in order of what matters:
          1. THE FLOOR STILL HOLDS in both lanes -- asserted here, and it is the
             part this feature owns.
          2. The allow-list decision belongs to ``sensitivity.py``, which this
             change deliberately does not touch. It is reported, not patched.
          3. The extension list is INCONSISTENT: ``.md`` is allow-listed,
             ``.markdown`` and ``.mdx`` are not (``".md"`` is not a substring of
             ``".markdown"``). Whatever the intended policy is, it is currently
             not the same for three spellings of one format.

        If ``sensitivity.py`` changes this, this test goes red -- which is the
        point. The change should be conscious, and whoever makes it should
        update this docstring rather than discover the behaviour later.
        """
        prose = "# Internal Plan\n\nUnreleased architecture notes.\n"
        # 1. the floor -- unconditional, both lanes, no bypass
        for lane in ("trusted", "untrusted"):
            self.assertIsNotNone(sensitivity.slice_egress_rule(
                "docs/leaky.md", textwrap.dedent(SECRET_DOC), lane=lane))
        # 2. observed allow-list behaviour for NON-secret prose
        self.assertIsNone(
            sensitivity.slice_egress_rule("notes/plan.md", prose, lane="untrusted"),
            "policy changed: .md is no longer untrusted-lane allow-listed")
        self.assertIsNotNone(
            sensitivity.slice_egress_rule("notes/plan.py", prose, lane="untrusted"),
            "policy changed: ordinary source is no longer default-denied")
        # 3. and the spelling inconsistency, recorded
        self.assertIsNotNone(
            sensitivity.slice_egress_rule("notes/plan.markdown", prose,
                                          lane="untrusted"),
            "policy changed: .markdown now matches the allow-list too")

    def test_the_index_itself_does_not_carry_the_secret(self):
        """The index is a local artifact, but it is handed to planners and
        serialised into receipts. Only counts and the title are stored."""
        blob = repr(self.idx)
        self.assertNotIn(AWS_KEY, blob)


# --------------------------------------------------------------------------- #
# 5. THE SLICE, END TO END                                                      #
# --------------------------------------------------------------------------- #
class DocumentSlice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _mkrepo({
            "pkg/mod.py": "def helper(x):\n    return x + 1\n",
            # "Storage" appears as a WORD in the Router section's prose and also
            # as a heading title. That collision is deliberate: it is what makes
            # the call-graph guard observable -- without it, resolving Router's
            # identifier tokens against the document's own heading table emits
            # the entire Storage section as a "callee".
            "docs/spec.md": (
                "# Spec\n\nThe design lives here.\n\n"
                "## Router\n\nThe router hands off to Storage for persistence.\n"
                + ("router prose\n" * 200) +
                "\nSee [the module](../pkg/mod.py).\n\n"
                "## Storage\n\n" + ("storage prose\n" * 200)
            ),
        })
        cls.idx = build_index(cls.root, documents=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_a_document_is_a_distillable_target(self):
        """It resolves, it gates, it expands its link neighbourhood.

        NOT asserted: a positive ``reduction_pct``. The FOCUS is emitted in full
        for a document exactly as for code, so on a two-file fixture where the
        document IS most of the repo the ratio is honestly negative. Asserting a
        win here would only pin the fixture's proportions.
        """
        res = semantic_slice(self.root, "docs/spec.md", idx=self.idx)
        self.assertEqual(res["focus_file"], "docs/spec.md")
        self.assertEqual(res["withheld"], [])
        self.assertIn("pkg/mod.py", [i["file"] for i in res["included"]])

    def test_addressing_a_heading_is_what_makes_a_big_document_cheap(self):
        """``spec.md::Router`` is the document analogue of ``mod.py::helper``,
        and it is where the reduction actually comes from on a real spec."""
        whole = semantic_slice(self.root, "docs/spec.md", idx=self.idx)
        part = semantic_slice(self.root, "docs/spec.md::Router", idx=self.idx)
        self.assertEqual(part["focus_symbol"], "Router")
        self.assertIn("router prose", part["slice_text"])
        self.assertNotIn("storage prose", part["slice_text"])
        self.assertLess(part["slice_tokens"], whole["slice_tokens"] * 0.7)
        self.assertGreater(part["reduction_pct"], whole["reduction_pct"])

    def test_an_anchor_slug_addresses_the_same_heading(self):
        a = semantic_slice(self.root, "docs/spec.md::Router", idx=self.idx)
        b = semantic_slice(self.root, "docs/spec.md::router", idx=self.idx)
        # The FOCUS header echoes the target string as written, so compare the
        # resolved body rather than the whole blob.
        self.assertEqual(a["slice_text"].split("\n", 1)[1],
                         b["slice_text"].split("\n", 1)[1])
        self.assertEqual(a["n_included"], b["n_included"])

    def test_a_document_neighbour_is_emitted_as_a_heading_tree_not_as_prose(self):
        """GUARD (``slice._skeleton``'s document branch). Without it the old
        fallthrough emitted twelve raw prose lines under a header reading
        "(skeleton)" -- a document presented as though it had signatures, with
        no statement that the rest of the file existed."""
        res = semantic_slice(self.root, "pkg/mod.py", idx=self.idx)
        blocks = [i for i in res["included"] if i["file"] == "docs/spec.md"]
        self.assertTrue(blocks, "the documenting file was not offered at all")
        self.assertEqual(blocks[0]["role"], "documented_by")
        self.assertIn("PROSE DROPPED", res["slice_text"])
        self.assertNotIn("router prose", res["slice_text"])

    def test_the_document_link_is_reported_under_its_own_role_not_as_an_import(self):
        res = semantic_slice(self.root, "docs/spec.md", idx=self.idx)
        roles = {i["role"] for i in res["included"]}
        self.assertIn("documents", roles)
        self.assertNotIn("dependency", roles)

    def test_prose_never_becomes_a_call_edge(self):
        """GUARD (``not is_doc`` on the symbol path). ``graph.callees`` matches
        identifier TOKENS; the resolver's same-file table for a document is that
        document's own headings, so without this guard any prose word equal to a
        heading title is emitted as a "callee" with its whole section body."""
        res = semantic_slice(self.root, "docs/spec.md::Router", idx=self.idx)
        self.assertNotIn("CALLEES", res["slice_text"])
        self.assertNotIn("CALLERS", res["slice_text"])


# --------------------------------------------------------------------------- #
# 6. OPT-IN, AND NO COLLATERAL DAMAGE TO THE CODE INDEX                         #
# --------------------------------------------------------------------------- #
# The two documents end with a BYTE-IDENTICAL section on purpose: it is the
# shape a clone pass would cluster, so "documents are never clone sites" is a
# claim this fixture can actually falsify rather than one it happens to satisfy.
SHARED_SECTION = "## Shared boilerplate\n\n" + ("an identical paragraph\n" * 8)
MIXED = {
    "pkg/mod.py": "def helper(x):\n    return x + 1\n",
    "pkg/user.py": "from pkg.mod import helper\n\n\ndef go():\n    return helper(1)\n",
    "README.md": ("# R\n\n" + ("prose\n" * 400) + "\nSee [mod](pkg/mod.py).\n\n"
                  + SHARED_SECTION),
    "docs/notes.md": "# N\n\n" + ("more prose\n" * 400) + "\n" + SHARED_SECTION,
}


class OptInAndIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _mkrepo(MIXED)
        cls.off = build_index(cls.root)
        cls.on = build_index(cls.root, documents=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_documents_are_off_by_default(self):
        """GUARD (``documents_enabled``). Default-on would move ``total_tokens``
        and therefore every published ``reduction_pct`` with no change to the
        slicer -- the flattering-denominator failure this repo already fixed."""
        self.assertFalse(documents_enabled())
        self.assertEqual(sorted(self.off["modules"]), ["pkg/mod.py", "pkg/user.py"])
        self.assertEqual(self.off["n_files"], 2)
        self.assertNotIn("documents", self.off)
        self.assertNotIn("document_links", self.off)
        self.assertNotIn("markdown", self.off["languages"])

    def test_the_env_var_turns_them_on(self):
        prior = os.environ.get("DAEDALUS_INDEX_DOCUMENTS")
        try:
            os.environ["DAEDALUS_INDEX_DOCUMENTS"] = "1"
            self.assertTrue(documents_enabled())
            os.environ["DAEDALUS_INDEX_DOCUMENTS"] = "0"
            self.assertFalse(documents_enabled())
            # an explicit argument always wins over the environment
            self.assertTrue(documents_enabled(True))
        finally:
            os.environ.pop("DAEDALUS_INDEX_DOCUMENTS", None)
            if prior is not None:
                os.environ["DAEDALUS_INDEX_DOCUMENTS"] = prior

    def test_turning_them_on_adds_documents_and_nothing_else(self):
        self.assertEqual(sorted(self.on["modules"]),
                         ["README.md", "docs/notes.md", "pkg/mod.py", "pkg/user.py"])
        self.assertEqual(self.on["n_files"], 4)
        self.assertEqual(self.on["languages"]["markdown"]["files"], 2)
        self.assertEqual(self.on["documents"]["count"], 2)
        # the code half is untouched
        self.assertEqual(self.on["import_edges"], self.off["import_edges"])
        self.assertEqual(self.on["fan_in"], self.off["fan_in"])
        self.assertEqual(self.on["duplication"], self.off["duplication"])
        self.assertEqual(self.on["dependencies"], self.off["dependencies"])

    def test_a_document_is_marked_as_one(self):
        entry = self.on["modules"]["README.md"]
        self.assertEqual(entry["kind"], md.DOCUMENT_KIND)
        self.assertEqual(entry["language"], "markdown")
        self.assertTrue(md.is_document(entry))
        self.assertFalse(md.is_document(self.on["modules"]["pkg/mod.py"]))
        # a source entry gains no "kind" key at all -> absence means source
        self.assertNotIn("kind", self.on["modules"]["pkg/mod.py"])

    def test_documents_are_never_hotspots(self):
        """GUARD (``score_modules`` over ``code_modules``). A 1,800-line handoff
        scores loc/50 = 36 with no code in it, and
        ``spine/picker.hotspot_candidates`` turns a hotspot row into a work item
        reading "extract the long functions" -- against a document."""
        for row in self.on["module_heat"] + self.on["hotspots"]:
            self.assertFalse(row["module"].endswith(".md"), row["module"])

    def test_documents_are_never_clone_sites(self):
        """400 identical prose lines in two files is not a refactoring target."""
        blob = repr(self.on["duplication"])
        self.assertNotIn(".md", blob)

    def test_a_link_is_not_an_import(self):
        self.assertNotIn("README.md", self.on["import_edges"])
        self.assertNotIn("README.md", self.on["fan_in"])
        self.assertEqual(self.on["document_links"], {"README.md": ["pkg/mod.py"]})
        self.assertEqual(self.on["document_links_reverse"],
                         {"pkg/mod.py": ["README.md"]})

    def test_documents_stay_out_of_the_safety_fences_denominator(self):
        """GUARD (``graph._graph_nodes`` over ``code_modules``). Documents have
        no import edges by construction, so every one of them lands in
        ``fenced_dominance``'s denominator and none in its numerator -- diluting
        a guardrail ``provider_router`` reads, for a bookkeeping reason."""
        self.assertEqual(graph_mod._graph_nodes(self.on),
                         graph_mod._graph_nodes(self.off))
        self.assertEqual(graph_mod.fenced_dominance(self.on, ("/pkg",))["fraction"],
                         graph_mod.fenced_dominance(self.off, ("/pkg",))["fraction"])

    def test_documents_stay_out_of_the_temporal_coupling_report(self):
        """GUARD (``churn.temporal_misses``' document filter). Docs and the code
        they describe co-change constantly and can NEVER have a static import
        edge, so every such pair would enter the "hidden coupling" report as a
        maximal-confidence miss."""
        pairs = [{"a": "README.md", "b": "pkg/mod.py", "pmi": 3.0,
                  "lift": 9.0, "count": 12},
                 {"a": "pkg/mod.py", "b": "pkg/other.py", "pmi": 2.0,
                  "lift": 4.0, "count": 5}]
        rows = temporal_misses(self.on, pairs)
        self.assertEqual([(r["a"], r["b"]) for r in rows],
                         [("pkg/mod.py", "pkg/other.py")])

    def test_spec_for_still_answers_None_for_markdown(self):
        """The invariant protecting thirteen call sites that read ``spec_for``
        as a CLAIM ("unit-level ground truth exists here"), including
        ``provider_router._looks_like_missed_source`` (non-None ⇒ escalate) and
        ``eval/harness._whole_repo_text`` (non-None ⇒ part of the published
        Tier-2 baseline)."""
        self.assertIsNone(spec_for("README.md"))
        self.assertIsNone(spec_for("a/b/c.markdown"))
        self.assertIsNotNone(doc_spec_for("README.md"))
        self.assertIsNone(doc_spec_for("mod.py"))

    def test_the_cache_cannot_serve_one_kind_of_index_for_the_other(self):
        """GUARD (``_scope_key``'s documents suffix). Same failure shape as the
        scope fingerprint: the feature silently not working in one process and
        silently working in the next."""
        self.assertNotEqual(self.on["scope_key"], self.off["scope_key"])
        a = cached_index(self.root)
        b = cached_index(self.root, documents=True)
        self.assertNotIn("README.md", a["modules"])
        self.assertIn("README.md", b["modules"])

    def test_the_build_is_deterministic(self):
        again = build_index(self.root, documents=True)
        self.assertEqual(sorted(again["modules"]), sorted(self.on["modules"]))
        self.assertEqual(again["document_links"], self.on["document_links"])
        self.assertEqual(build_knowledge_forest(again).content_sha256,
                         build_knowledge_forest(self.on).content_sha256)

    def test_documents_obey_the_declared_center_like_any_other_file(self):
        """A new node kind does not get to walk around the scope boundary. A
        vendored/spec-copy doc tree is shell for exactly the reasons a vendored
        source tree is, and it is COUNTED as withheld rather than dropped
        silently."""
        scoped = build_index(self.root, center=["pkg"], documents=True)
        self.assertNotIn("README.md", scoped["modules"])
        self.assertNotIn("docs/notes.md", scoped["modules"])
        self.assertEqual(scoped["documents"]["count"], 0)
        self.assertEqual(scoped["documents"]["n_scanned"], 2)
        self.assertEqual(scoped["documents"]["ignored_count"], 2)
        self.assertIn("README.md", scoped["ignored"]["sample"])
        # ...and a shell document is therefore not an expansion target either
        self.assertEqual(scoped.get("document_links"), {})

    def test_ignore_patterns_bound_the_document_set(self):
        """The operator's lever, and the answer to "won't this pull in every
        transcript?". Documents go through the same ``.daedalusignore``/
        ``--ignore`` machinery as source, so a repo can index its design docs
        without indexing its logs. Verified on this repo: 61 documents -> 50
        with ``--ignore runs/*``, and no ``runs/`` document survives."""
        bounded = build_index(self.root, ignore=["docs/*"], documents=True)
        docs = [m for m, a in bounded["modules"].items() if md.is_document(a)]
        self.assertEqual(docs, ["README.md"])

    def test_exclusions_are_reported_never_silent(self):
        block = self.on["documents"]
        self.assertTrue(block["enabled"])
        for name in ("duplication", "fan_in", "hotspots", "import_edges",
                     "module_heat"):
            self.assertIn(name, block["excluded_from"])
        self.assertIn("n_links_unresolved", block)
        self.assertIn("n_links_external", block)


# --------------------------------------------------------------------------- #
# 7. THE FOREST AND THE SELECTOR — the defect, end to end                       #
# --------------------------------------------------------------------------- #
class ForestAndSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _mkrepo(MIXED)
        cls.idx = build_index(cls.root, documents=True)
        cls.forest = build_knowledge_forest(cls.idx)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_a_document_is_a_document_node_not_a_source_file_node(self):
        """GUARD (``forest``'s kind discriminator). Labelling a README
        "source_file" pushes the lie into every consumer that keys off
        ``node.kind`` -- and those are exactly the consumers that need to tell
        prose from code."""
        kinds = {n.id: n.kind for n in self.forest.nodes}
        self.assertEqual(kinds["README.md"], "document")
        self.assertEqual(kinds["docs/notes.md"], "document")
        self.assertEqual(kinds["pkg/mod.py"], "source_file")

    def test_links_are_their_own_relation_layer(self):
        layers = self.forest.layer_counts
        self.assertEqual(layers.get("documents"), 1)
        edge = next(e for e in self.forest.edges if e.relation == "documents")
        self.assertEqual((edge.source, edge.target), ("README.md", "pkg/mod.py"))
        self.assertEqual(edge.evidence, ("structcore.document_links",))
        # and it did NOT contaminate the imports layer
        self.assertNotIn(("README.md", "pkg/mod.py"),
                         [(e.source, e.target) for e in self.forest.edges
                          if e.relation == "imports"])

    def test_a_document_carries_a_token_cost_the_planner_can_budget_with(self):
        node = next(n for n in self.forest.nodes if n.id == "README.md")
        self.assertGreater(int(node.attributes["n_tokens"]), 0)

    def test_a_document_is_a_leaf_of_the_selection_hierarchy(self):
        paths = {n.path for n in build_forest_hierarchy(self.forest).nodes
                 if n.kind == "file"}
        self.assertIn("README.md", paths)
        self.assertIn("docs/notes.md", paths)

    def test_the_selector_can_actually_choose_a_document(self):
        """THE DEFECT, AS A TEST. ``FILE_NODE_KINDS`` has to contain "document"
        in all three places at once; a kind accepted as a seed but rejected as a
        hierarchy leaf raises ``KeyError: unknown Forest file ID``. This is what
        it means for a specification to be visible to the context planner."""
        self.assertIn("document", FILE_NODE_KINDS)
        result = semantic_super_sample(
            self.forest, {"README.md": 1.0}, token_budget=100000)
        chosen = {item.node_id for item in result.context_plan.selected}
        self.assertIn("README.md", chosen)
        # ...and the document's own token cost, not a loc*8 guess, was budgeted
        item = next(i for i in result.context_plan.selected
                    if i.node_id == "README.md")
        self.assertEqual(item.estimated_tokens,
                         int(self.idx["modules"]["README.md"]["n_tokens"]))

    def test_heading_titles_reach_the_lexical_corpus(self):
        """The mechanism that makes a spec RANKABLE, not merely present: the
        symbol resolver's ``defs_by_file`` is what ``context_plan._symbol_names``
        reads to build the BM25 corpus."""
        from daedalus.structcore.index import resolution_context

        resolver = resolution_context(self.root, key=self.idx["scope_key"])
        self.assertIsNotNone(resolver)
        self.assertIn("R", resolver.defs_by_file.get("README.md", {}))

    def test_a_spec_is_found_by_its_HEADINGS_not_only_by_its_path(self):
        """Isolates which mechanism actually fixes the defect.

        Being a node is necessary but not sufficient: a document whose FILENAME
        carries none of the objective's words has to be findable by what it
        SAYS. Here the file is ``notes/d17.md`` -- no query term in the path --
        and the only evidence connecting it to the objective is a heading. This
        is worth pinning separately because the link layer, the other candidate
        mechanism, is nearly empty on real repos: this codebase's documents
        reference code in backticks rather than markdown links, so the whole
        repo yields 6 intra-repo link edges across 61 documents. The node and
        its headings are what carry the fix; the link layer is a bonus.
        """
        from daedalus.context_plan import plan_context

        root = _mkrepo({
            "pkg/a.py": "def alpha():\n    return 1\n",
            "pkg/b.py": "def beta():\n    return 2\n",
            "notes/d17.md": "# Overview\n\nprose\n\n"
                            "## Quiescent Handshake Protocol\n\n"
                            + ("design prose\n" * 40),
        })
        try:
            objective = "implement the quiescent handshake protocol"
            plain = plan_context(root, objective, token_budget=20000,
                                 idx=build_index(root))
            withdocs = plan_context(root, objective, token_budget=20000,
                                    idx=build_index(root, documents=True))
            self.assertNotIn("notes/d17.md",
                             [i.node_id for i in plain.dss.context_plan.selected])
            chosen = [i.node_id for i in withdocs.dss.context_plan.selected]
            self.assertIn("notes/d17.md", chosen)
            self.assertEqual(chosen[0], "notes/d17.md")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_heading_never_resolves_a_code_identifier(self):
        """The other half of that mechanism: nothing IMPORTS a document, so a
        heading can only ever be resolved from the document itself."""
        from daedalus.structcore.index import resolution_context

        resolver = resolution_context(self.root, key=self.idx["scope_key"])
        self.assertIsNone(resolver.resolve("R", "pkg/mod.py"))
        self.assertIsNone(resolver.resolve("helper", "docs/notes.md"))


if __name__ == "__main__":
    unittest.main()
