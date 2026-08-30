# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""test_mint_label_hygiene.py -- lane A1 label hygiene: JUNK filter,
CROSS-LANGUAGE filter, and FLOOR-TRIPPING ANCHOR EXCLUSION inside
``daedalus.eval.mint._mint_from_diffs`` (see that module's docstring, "LABEL
HYGIENE" section).

The independent quarantine recall printed 61.7% over 18 minted tasks; a
scripted triage of the 129 misses found the majority were the secret floor
fail-closing on credential-fixture targets (working as designed, not a
slicer defect) and cross-language/parser-junk names (measuring nothing about
the slicer being graded) -- not genuine slicer failures. These tests pin that
each of those three classes is now caught BEFORE it can corrupt the honest
recall number, and that every drop is RECORDED, never silent.

Two isolation strategies, matching the existing house style in
tests/test_eval_mint.py's ``MintFromDiffsScopeAndLabelTest``:
  * JUNK / CROSS-LANGUAGE: ``_diffed_symbols`` is mocked so the exact symbol
    names reaching the filter are controlled directly -- real language
    grammars won't hand back a bare ``if`` or ``<anonymous>`` from valid
    Python source, so this isolates the FILTER RULE from parser quirks.
  * FLOOR-TRIPPING ANCHOR EXCLUSION: real, unmocked ``_diffed_symbols`` +
    a planted-credential literal reused verbatim from
    tests/test_slice_secret_value_shape.py's pinned fixture, so the
    ``secret_floor_rule`` call inside ``_mint_from_diffs`` fires for real.

Offline only: no git, no network, no real Claude/Ollama call.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus.eval import harness, mint, report


class _NonRepoMintRoot(unittest.TestCase):
    """Give pure mint tests a root that is not the verifier's linked worktree."""

    def setUp(self):
        self._mint_root_tmp = tempfile.TemporaryDirectory()
        self.repo_root = self._mint_root_tmp.name

    def tearDown(self):
        self._mint_root_tmp.cleanup()


# --------------------------------------------------------------------------- #
# 1. JUNK FILTER                                                              #
# --------------------------------------------------------------------------- #
class JunkLabelFilterTest(_NonRepoMintRoot):
    """Isolates the JUNK FILTER by mocking ``_diffed_symbols`` directly: real
    extractors CAN legitimately hand back ``<anonymous>`` (inline JS/TS arrow,
    parse.py's ``_ANON``) or a bare keyword-shaped node text on some grammar
    edge case -- this proves ``_mint_from_diffs`` refuses to ever mint either
    as a ``must_include`` label, however it got there."""

    def test_junk_names_filtered_and_recorded(self):
        def fake_diffed_symbols(rel, before, after):
            if rel == "a.py":
                # 4 raw symbols -- wins the (unfiltered) anchor race over
                # b.py's 4 by the path tie-break ("a.py" < "b.py").
                return {"real_anchor_func": 3, "extra1": 1, "extra2": 1, "extra3": 1}
            if rel == "b.py":
                return {"real_label": 2, "if": 1, "<anonymous>": 1, "123bad": 1}
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, diag = mint._mint_from_diffs(
                {"a.py": ("old", "new"), "b.py": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"a.py", "b.py"}),
            )
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "a.py")
        # Only the plausible identifier survives into must_include.
        self.assertEqual(task["must_include"], ["real_label"])
        self.assertEqual(task["labels_filtered_junk"], ["123bad", "<anonymous>", "if"])
        self.assertEqual(task["labels_filtered_cross_language"], [])
        self.assertEqual(diag["skipped_out_of_scope"], [])

    def test_is_junk_label_pinned_shapes(self):
        # Pins the exact rule -- not-an-identifier OR an EXACT-CASE keyword
        # (case-sensitive: real reserved words are fixed-case in every
        # supported language), so a bump to the denylist/regex is a
        # deliberate diff.
        for junk in ("if", "return", "<anonymous>", "123bad", "", "a-b", "a.b"):
            self.assertTrue(mint._is_junk_label(junk), junk)
        for real in ("helper", "_private", "Engine2", "camelCaseName", "SCREAMING_SNAKE"):
            self.assertFalse(mint._is_junk_label(real), real)

    def test_pascal_case_of_a_keyword_is_not_junk(self):
        # Regression (A1 repair, MEDIUM #4): the keyword check used to be
        # case-FOLDED, so "For"/"RETURN" (legal Python/Go/etc identifiers --
        # Python's own keyword is "for"/"return", never capitalized) were
        # wrongly flagged as junk. Case-sensitivity fixes that without
        # weakening the exact-case match real grammar-recovery noise needs.
        for real in ("For", "RETURN", "Return", "If"):
            self.assertFalse(mint._is_junk_label(real), real)

    def test_language_ambiguous_words_are_no_longer_universally_junk(self):
        # Regression (A1 repair, MEDIUM #4): "delete" (a legal Python/Django
        # method name -- Python's keyword is "del", not "delete"), "New" (Go's
        # idiomatic exported constructor), "Default"/"Case"/"Switch" (legal
        # C#/Java member and class names) were dropped by the old universal
        # denylist even though none of them are reserved words in every
        # supported language. They must survive the junk filter now.
        for real in ("delete", "New", "Default", "Case", "Switch"):
            self.assertFalse(mint._is_junk_label(real), real)

    def test_identifier_shape_allows_unicode_and_dollar(self):
        # Regression (A1 repair, MEDIUM #4): the old ASCII-only identifier
        # regex rejected legal non-ASCII Python identifiers and legal JS/TS
        # ``$``-prefixed/-embedded identifiers (e.g. Angular's ``$scope``).
        for real in ("café", "$scope", "a$b", "$"):
            self.assertFalse(mint._is_junk_label(real), real)
        # Still rejects genuine non-identifier shapes.
        for junk in ("a b", "a!b", "1abc"):
            self.assertTrue(mint._is_junk_label(junk), junk)


# --------------------------------------------------------------------------- #
# 2. CROSS-LANGUAGE FILTER                                                    #
# --------------------------------------------------------------------------- #
class CrossLanguageLabelFilterTest(_NonRepoMintRoot):
    """A label may only come from a file whose ``languages.spec_for`` language
    FAMILY matches the TARGET's -- a TypeScript symbol co-committed alongside
    a Python target measures nothing about the Python slicer being graded."""

    def test_mismatched_language_label_filtered_and_recorded(self):
        def fake_diffed_symbols(rel, before, after):
            if rel == "a.py":
                return {"anchor_sym": 5, "x2": 1, "x3": 1}  # 3 syms -> anchor
            if rel == "b.py":
                return {"good_label": 2}  # same language (python) as target
            if rel == "c.ts":
                return {"ts_label": 2}  # different language -> filtered
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, _ = mint._mint_from_diffs(
                {"a.py": ("old", "new"), "b.py": ("old", "new"), "c.ts": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"a.py", "b.py", "c.ts"}),
            )
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "a.py")
        self.assertEqual(task["must_include"], ["good_label"])
        self.assertEqual(task["labels_filtered_cross_language"], ["ts_label"])
        self.assertEqual(task["labels_filtered_junk"], [])

    def test_same_language_different_extension_is_not_filtered(self):
        # .py and .pyi are both the "python" LanguageSpec -- this is NOT a
        # same-file check (that's CROSS-FILE ONLY, untouched), only a
        # same-LANGUAGE check.
        def fake_diffed_symbols(rel, before, after):
            if rel == "a.py":
                return {"anchor_sym": 5, "x2": 1}
            if rel == "b.pyi":
                return {"stub_label": 2}
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, _ = mint._mint_from_diffs(
                {"a.py": ("old", "new"), "b.pyi": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"a.py", "b.pyi"}),
            )
        self.assertIsNotNone(task)
        self.assertEqual(task["must_include"], ["stub_label"])
        self.assertEqual(task["labels_filtered_cross_language"], [])


# --------------------------------------------------------------------------- #
# 2b. LANGUAGE FAMILY (A1 repair, MEDIUM #2)                                  #
# --------------------------------------------------------------------------- #
class LanguageFamilyCrossFileTest(_NonRepoMintRoot):
    """Regression: the cross-language filter used to compare
    ``LanguageSpec.name`` by exact equality, so a C++ file's own header
    (spec "c" vs spec "cpp") or a TypeScript file's own imported JS module
    (spec "typescript" vs "javascript") were wrongly classified as
    cross-language, even though the slicer's own import graph resolves
    exactly that ``#include``/``import`` edge and would emit the neighbour's
    text -- deflating recall's denominator for a genuinely recallable label,
    and feeding the empty-``must_include`` guard when it was the only other
    changed file. Real extensions (unmocked ``spec_for``); only
    ``_diffed_symbols`` is mocked, matching the house isolation strategy."""

    def test_cpp_header_label_kept_for_cpp_target(self):
        def fake_diffed_symbols(rel, before, after):
            if rel == "main.cpp":
                return {"anchor_sym": 5, "x2": 1, "x3": 1}  # wins anchor race
            if rel == "util.h":
                return {"helper_fn": 2}  # spec "c", same family as "cpp"
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, _ = mint._mint_from_diffs(
                {"main.cpp": ("old", "new"), "util.h": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"main.cpp", "util.h"}),
            )
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "main.cpp")
        self.assertEqual(task["must_include"], ["helper_fn"])
        self.assertEqual(task["labels_filtered_cross_language"], [])

    def test_js_label_kept_for_ts_target(self):
        def fake_diffed_symbols(rel, before, after):
            if rel == "app.ts":
                return {"anchor_sym": 5, "x2": 1, "x3": 1}
            if rel == "helper.js":
                return {"jsHelper": 2}  # spec "javascript", same family as "typescript"
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, _ = mint._mint_from_diffs(
                {"app.ts": ("old", "new"), "helper.js": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"app.ts", "helper.js"}),
            )
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "app.ts")
        self.assertEqual(task["must_include"], ["jsHelper"])
        self.assertEqual(task["labels_filtered_cross_language"], [])

    def test_truly_different_family_is_still_filtered(self):
        # A C header is NOT the same family as Python -- family grouping is
        # narrow (only the pairs the slicer's own import graph crosses), not
        # a general relaxation of the filter. b.py is a second, same-language
        # label source so the filtered-out util.h symbol is visible on a
        # minted task rather than tripping the (separately pinned) empty-
        # must_include guard.
        def fake_diffed_symbols(rel, before, after):
            if rel == "main.py":
                return {"anchor_sym": 5, "x2": 1, "x3": 1}
            if rel == "b.py":
                return {"good_label": 2}
            if rel == "util.h":
                return {"helper_fn": 2}
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, _ = mint._mint_from_diffs(
                {"main.py": ("old", "new"), "b.py": ("old", "new"), "util.h": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"main.py", "b.py", "util.h"}),
            )
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "main.py")
        self.assertEqual(task["must_include"], ["good_label"])
        self.assertEqual(task["labels_filtered_cross_language"], ["helper_fn"])


# --------------------------------------------------------------------------- #
# 3. FLOOR-TRIPPING LABEL SOURCE EXCLUSION                                    #
# --------------------------------------------------------------------------- #
class FloorTrippingAnchorExclusionTest(_NonRepoMintRoot):
    """A file whose current content trips the unconditional secret floor can
    never be a meaningful slice target (semantic_slice's FOCUS GATE fails it
    closed) -- excluded from the ANCHOR POOL, per the module docstring. A1
    repair (MEDIUM #3): it is ALSO excluded as a cross-file label SOURCE now
    -- semantic_slice's egress gate withholds a floor-tripping file as a
    NEIGHBOUR in every lane too (slice.py's ``_emit_ok``), so a symbol
    defined only there can never appear in any slice; keeping it in
    ``must_include`` was a guaranteed, permanent recall miss mislabeled as a
    slicer defect. Credential literal reused verbatim from
    tests/test_slice_secret_value_shape.py's pinned fixture."""

    _CRED_V1 = "def helper_a(x):\n    return x + 1\n\ndef helper_b(y):\n    return y - 1\n"
    _CRED_V2 = (
        "def helper_a(x):\n    return x + 100\n\n"
        "def helper_b(y):\n    return y - 100\n\n"
        'API_KEY = "sekret_live_value_do_not_share_1234"\n'
    )
    _OTHER_V1 = "def other_func(y):\n    return y - 1\n"
    _OTHER_V2 = "def other_func(y):\n    return y - 1 if y else 0\n"

    def test_floor_tripping_file_excluded_from_anchor_pool_and_label_source(self):
        files = {
            # cred.py has 3 diffed symbols -- would win BOTH the anchor race
            # AND contribute the most labels if not excluded on both counts.
            "cred.py": (
                self._CRED_V1.replace(
                    "return y - 1\n", "return y - 1\n\ndef helper_c(z):\n    return z\n"),
                self._CRED_V2.replace(
                    'API_KEY = "sekret_live_value_do_not_share_1234"\n',
                    'API_KEY = "sekret_live_value_do_not_share_1234"\n\n'
                    "def helper_c(z):\n    return z * 2\n"),
            ),
            "other.py": (
                "def other_func(y):\n    return y - 1\n\ndef other_func2(y):\n    return y\n",
                "def other_func(y):\n    return y - 1 if y else 0\n\ndef other_func2(y):\n    return y + 1\n",
            ),
            "clean.py": (
                "def clean_func(y):\n    return y - 1\n",
                "def clean_func(y):\n    return y - 1 if y else 0\n",
            ),
        }
        task, diag = mint._mint_from_diffs(
            files, repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"cred.py", "other.py", "clean.py"}),
        )
        self.assertIsNotNone(task)
        # other.py (2 diffed syms, healthy) wins the anchor race over
        # clean.py (1 sym) -- cred.py (3 syms) is excluded despite the
        # largest raw count, proving exclusion actually changed the anchor.
        self.assertEqual(task["target"], "other.py")
        self.assertEqual(task["skipped_secret_floor"], ["cred.py"])
        # cred.py's symbols are FILTERED, not kept -- the corrected behavior.
        self.assertNotIn("helper_a", task["must_include"])
        self.assertNotIn("helper_b", task["must_include"])
        self.assertNotIn("helper_c", task["must_include"])
        self.assertEqual(task["must_include"], ["clean_func"])
        self.assertEqual(
            task["labels_filtered_secret_floor"], ["helper_a", "helper_b", "helper_c"])
        self.assertEqual(diag["skipped_secret_floor"], ["cred.py"])

    def test_floor_tripping_only_label_source_mints_nothing_with_reason(self):
        # Regression (A1 repair, HIGH #1 x MEDIUM #3 interaction): cred.py is
        # the ONLY other in-scope file besides the anchor -- once its symbols
        # are correctly excluded as a label source, no cross-file label
        # survives at all, so this must mint NOTHING (not a must_include=[]
        # task), with the drop recorded in diagnostics since there is no task
        # dict to carry it on.
        files = {
            "cred.py": (self._CRED_V1, self._CRED_V2),
            "other.py": (self._OTHER_V1, self._OTHER_V2),
        }
        task, diag = mint._mint_from_diffs(
            files, repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"cred.py", "other.py"}),
        )
        self.assertIsNone(task)
        self.assertEqual(diag["skipped_secret_floor"], ["cred.py"])
        self.assertEqual(diag["labels_filtered_secret_floor"], ["helper_a", "helper_b"])
        self.assertIn("secret-floor", diag["reason"])

    def test_all_candidates_floor_tripping_mints_nothing_with_reason(self):
        files = {
            "cred_a.py": (self._CRED_V1, self._CRED_V2),
            "cred_b.py": (
                self._CRED_V1.replace("helper_a", "helper_c").replace("helper_b", "helper_d"),
                self._CRED_V2.replace("helper_a", "helper_c").replace("helper_b", "helper_d"),
            ),
        }
        task, diag = mint._mint_from_diffs(
            files, repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"cred_a.py", "cred_b.py"}),
        )
        self.assertIsNone(task)
        self.assertEqual(sorted(diag["skipped_secret_floor"]), ["cred_a.py", "cred_b.py"])
        self.assertIn("secret floor", diag["reason"])


# --------------------------------------------------------------------------- #
# 4. Determinism                                                              #
# --------------------------------------------------------------------------- #
class MintDeterminismTest(_NonRepoMintRoot):
    def test_repeated_mint_of_same_diff_is_identical(self):
        files = {
            "a.py": ("def f():\n    return 1\n", "def f():\n    return 2\n"),
            "b.py": ("def g():\n    return 1\n", "def g():\n    return 3\n"),
        }
        kwargs = dict(repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                      in_scope=frozenset({"a.py", "b.py"}))
        task1, diag1 = mint._mint_from_diffs(dict(files), **kwargs)
        task2, diag2 = mint._mint_from_diffs(dict(files), **kwargs)
        self.assertEqual(task1, task2)
        self.assertEqual(diag1, diag2)


# --------------------------------------------------------------------------- #
# 5. Regression: a clean diff mints byte-identically to before this lane      #
# --------------------------------------------------------------------------- #
class CleanMintByteIdenticalRegressionTest(_NonRepoMintRoot):
    """A diff with zero junk names, zero cross-language labels, and zero
    secret-floor-tripping candidates must mint EXACTLY what mint.py minted
    before these three filters existed -- the same fixture values as
    tests/test_eval_mint.py's MintFromCommitTest -- with the three new fields
    present but empty (additive, not a behavior change)."""

    def test_clean_cross_file_diff_is_unaffected(self):
        files = {
            "mod.py": (
                "def helper(x):\n    return x + 1\n\ndef target_func(x):\n    return helper(x) * 2\n",
                "def helper(x):\n    return x + 1\n\ndef target_func(x):\n    return helper(x) * 3 + 1\n",
            ),
            "other.py": (
                "def other_func(y):\n    return y - 1\n",
                "def other_func(y):\n    return y - 1 if y else 0\n",
            ),
        }
        task, _ = mint._mint_from_diffs(
            files, repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"mod.py", "other.py"}))
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "mod.py::target_func")
        self.assertEqual(task["must_include"], ["other_func"])
        self.assertEqual(task["must_include_dropped"], 0)
        self.assertEqual(task["skipped_out_of_scope"], [])
        self.assertEqual(task["labels_filtered_junk"], [])
        self.assertEqual(task["labels_filtered_cross_language"], [])
        self.assertEqual(task["labels_filtered_secret_floor"], [])
        self.assertEqual(task["skipped_secret_floor"], [])


# --------------------------------------------------------------------------- #
# 5b. Regression: label hygiene emptying every cross-file candidate mints     #
#     NOTHING, never a vacuous must_include=[] task (A1 repair, HIGH #1)      #
# --------------------------------------------------------------------------- #
class EmptyMustIncludeGuardTest(_NonRepoMintRoot):
    """Before this fix, ``_mint_from_diffs`` re-checked non-emptiness of
    ``per_file`` BEFORE label hygiene filtering but never AFTER -- so a
    commit whose only cross-file symbols were all junk, all cross-language,
    or all sourced from a floor-tripping file minted a task with
    ``must_include=[]``, which ``harness._recall`` scores as a vacuous 1.0
    (see the module docstring's CROSS-FILE ONLY invariant: "it mints nothing
    rather than minting a label=[] task"). These pin that the guard now
    fires for the JUNK and CROSS-LANGUAGE paths (the secret-floor path is
    covered by ``FloorTrippingAnchorExclusionTest.
    test_floor_tripping_only_label_source_mints_nothing_with_reason``)."""

    def test_all_cross_file_symbols_junk_mints_nothing(self):
        def fake_diffed_symbols(rel, before, after):
            if rel == "a.py":
                return {"real_anchor_func": 3, "extra1": 1, "extra2": 1, "extra3": 1}
            if rel == "b.py":
                # Every candidate is junk -- no real label survives.
                return {"if": 1, "<anonymous>": 1, "123bad": 1}
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, diag = mint._mint_from_diffs(
                {"a.py": ("old", "new"), "b.py": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"a.py", "b.py"}),
            )
        self.assertIsNone(task)
        self.assertEqual(diag["labels_filtered_junk"], ["123bad", "<anonymous>", "if"])
        self.assertEqual(diag["labels_filtered_cross_language"], [])
        self.assertIn("label hygiene", diag["reason"])

    def test_all_cross_file_symbols_cross_language_mints_nothing(self):
        def fake_diffed_symbols(rel, before, after):
            if rel == "a.py":
                return {"anchor_sym": 5, "x2": 1, "x3": 1}
            if rel == "c.ts":
                # Only cross-file source is a different-family language.
                return {"ts_label": 2}
            return {}

        with mock.patch("daedalus.eval.mint._diffed_symbols", side_effect=fake_diffed_symbols):
            task, diag = mint._mint_from_diffs(
                {"a.py": ("old", "new"), "c.ts": ("old", "new")},
                repo_root=self.repo_root, minted_at_sha="deadbeef", source="commit",
                in_scope=frozenset({"a.py", "c.ts"}),
            )
        self.assertIsNone(task)
        self.assertEqual(diag["labels_filtered_cross_language"], ["ts_label"])
        self.assertEqual(diag["labels_filtered_junk"], [])
        self.assertIn("label hygiene", diag["reason"])

    def test_recall_would_have_been_vacuous_one_pre_fix_shape(self):
        # Direct pin of the exact failure mode described in the finding:
        # harness._recall on an empty must_include is a vacuous 1.0. This
        # confirms the guard is what stands between "all labels filtered"
        # and that vacuous score reaching a report.
        self.assertEqual(harness._recall("anything at all", []), (1.0, []))


# --------------------------------------------------------------------------- #
# 6. Eval target: focus_withheld end-to-end (mint.py's floor rule feeds the   #
#    same fence eval_task_tier1 checks -- exercised here at the harness/gate/ #
#    report layer against a real semantic_slice run).                        #
# --------------------------------------------------------------------------- #
def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


_CORE_CLEAN = "def helper2(x):\n    return x + 1\n"
_SECRET_FILE = (
    "def helper(x):\n"
    "    return x * 2\n"
    "\n"
    'API_KEY = "sekret_live_value_do_not_share_1234"\n'
)


class FocusWithheldEvalTargetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", _CORE_CLEAN)
        _write(self.root, "proj/secret.py", _SECRET_FILE)
        repo = str(self.root)
        self.healthy_task = {
            "id": "healthy", "repo": repo, "target": "proj/core.py",
            "must_include": ["helper2"],
            "label_provenance": "hand_reachable", "tier": "primary",
        }
        self.secret_task = {
            "id": "focus_withheld_task", "repo": repo, "target": "proj/secret.py",
            "must_include": ["helper"],
            "label_provenance": "hand_reachable", "tier": "primary",
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_tier1_row_is_focus_withheld_never_scored(self):
        row = harness.eval_task_tier1(self.secret_task)
        self.assertTrue(row.get("focus_withheld"))
        self.assertNotIn("recall", row)
        self.assertNotIn("compression", row)
        self.assertNotIn("missed", row)

    def test_run_tier1_excludes_from_mean_and_counts_it(self):
        result = harness.run_tier1([self.healthy_task, self.secret_task])
        self.assertEqual(result["n_focus_withheld"], 1)
        self.assertEqual(result["focus_withheld_ids"], ["focus_withheld_task"])
        bp = result["by_provenance"]["hand_reachable"]["primary"]
        self.assertEqual(bp["n_tasks"], 1)  # only the healthy task counted
        self.assertEqual(bp["mean_recall"], 1.0)
        by_id = {t["id"]: t for t in result["per_task"]}
        self.assertTrue(by_id["focus_withheld_task"].get("focus_withheld"))

    def test_gate_does_not_flag_transition_to_focus_withheld(self):
        baseline_path = str(self.root / "baseline.json")
        with open(baseline_path, "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "tasks": {
                "healthy": {"recall": 1.0, "label_provenance": "hand_reachable", "tier": "primary"},
                "focus_withheld_task": {"recall": 1.0, "label_provenance": "hand_reachable", "tier": "primary"},
            }}, fh)
        gate = harness.run_gate([self.healthy_task, self.secret_task], baseline_path=baseline_path)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["regressions"], [])
        self.assertEqual([r["id"] for r in gate["focus_withheld"]], ["focus_withheld_task"])

    def test_snapshot_baseline_skips_focus_withheld_task(self):
        snap = harness.snapshot_baseline([self.healthy_task, self.secret_task])
        self.assertIn("healthy", snap["tasks"])
        self.assertNotIn("focus_withheld_task", snap["tasks"])

    def test_report_renders_focus_withheld_section(self):
        result = harness.run_tier1([self.healthy_task, self.secret_task])
        text = report.render_tier1(result)
        text.encode("ascii")  # cp1252 console safety
        self.assertIn("FOCUS-WITHHELD", text)
        self.assertIn("focus_withheld_task", text)
        self.assertIn("not a recall miss, not a pass", text)

    def test_gate_report_renders_focus_withheld_section(self):
        baseline_path = str(self.root / "baseline.json")
        gate = harness.run_gate([self.healthy_task, self.secret_task], baseline_path=baseline_path)
        text = report.render_gate(gate)
        text.encode("ascii")
        self.assertIn("FOCUS-WITHHELD", text)
        self.assertIn("focus_withheld_task", text)
        self.assertIn("PASS", text)


if __name__ == "__main__":
    unittest.main()
