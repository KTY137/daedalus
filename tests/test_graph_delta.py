"""The measurement's own contract.

The most important test in this file is ``test_a_comment_alone_does_not_move_the
_clean_arm``. The first run of ``graph_delta`` reported 10/12 detected and every
single detection contained the tokens ``SEEDED`` and ``DEFECT`` — the marker words
the mutation corpus writes into its own replacement comments. The measurement was
detecting its own label. That class of self-prediction artefact is the one
``eval/ceiling.py`` exists to separate, and it is easy to reintroduce, so it is
pinned here.
"""
from __future__ import annotations

import unittest

from daedalus.eval import graph_delta as gd


class TheCleanArmIgnoresComments(unittest.TestCase):
    def test_a_comment_alone_does_not_move_the_clean_arm(self):
        before = "def f(x):\n    return helper(x)\n"
        after = "def f(x):\n    # SEEDED DEFECT: guard disabled by the corpus\n    return helper(x)\n"
        refs_b, err_b = gd._ast_refs("m.py", before)
        refs_a, err_a = gd._ast_refs("m.py", after)
        self.assertEqual(err_b, "")
        self.assertEqual(err_a, "")
        self.assertEqual(refs_a, refs_b,
                         "a comment is not a program token; the clean arm must not move")

    def test_the_leaky_arm_DOES_move_on_a_comment(self):
        """Kept deliberately: the gap between the arms is the measured size of
        the artefact, so the leaky behaviour has to stay observable."""
        before = "def f(x):\n    return helper(x)\n"
        after = "def f(x):\n    # SEEDED DEFECT here\n    return helper(x)\n"
        _, leak_b = gd._units_and_refs("m.py", before)
        _, leak_a = gd._units_and_refs("m.py", after)
        self.assertNotEqual(leak_a, leak_b)

    def test_a_docstring_is_not_a_reference_either(self):
        before = 'def f(x):\n    """Calls helper."""\n    return helper(x)\n'
        after = 'def f(x):\n    """Calls helper and validates nothing at all."""\n    return helper(x)\n'
        self.assertEqual(gd._ast_refs("m.py", before)[0], gd._ast_refs("m.py", after)[0])

    def test_the_leaky_layer_cannot_score_a_detection(self):
        self.assertNotIn("code.refs.leaky", gd.DeltaResult.SCORING_LAYERS,
                         "scoring on raw source would make every mutation a tautology")


class MultisetSemantics(unittest.TestCase):
    def test_deleting_one_of_two_identical_calls_is_visible(self):
        """Set semantics hid exactly this, and it is the shape of a seeded defect:
        'this function now calls the guard once instead of twice'."""
        before = "def f(a, b):\n    check(a)\n    check(b)\n    return a\n"
        after = "def f(a, b):\n    check(a)\n    return a\n"
        rb, _ = gd._ast_refs("m.py", before)
        ra, _ = gd._ast_refs("m.py", after)
        self.assertTrue(rb - ra, "one of the two calls disappeared and must show")

    def test_an_unchanged_body_moves_nothing(self):
        src = "def f(a):\n    return check(a) + check(a)\n"
        self.assertEqual(gd._ast_refs("m.py", src)[0], gd._ast_refs("m.py", src)[0])


class UnparseableIsReported(unittest.TestCase):
    def test_broken_syntax_returns_a_reason_not_an_empty_set(self):
        refs, err = gd._ast_refs("m.py", "def f(:\n")
        self.assertEqual(refs, set())
        self.assertIn("unparseable", err,
                      "an empty ref set with no reason reads as 'nothing changed'")


class FunctionGranularity(unittest.TestCase):
    """A defect edits one function; a commit may touch a thousand lines around it."""

    def test_a_deletion_is_not_masked_by_growth_elsewhere(self):
        before = ("def guarded(x):\n    verify(x)\n    return x\n"
                  "def other(y):\n    return y\n")
        after = ("def guarded(x):\n    return x\n"
                 "def other(y):\n    return helper(y) + helper(y) + helper(y)\n")
        rows = {r["function"]: r for r in gd.function_deltas(before, after)}
        self.assertEqual(rows["guarded"]["added"], 0)
        self.assertGreater(rows["guarded"]["removed"], 0,
                           "the guarded function lost a call and must say so")
        self.assertGreater(rows["other"]["added"], 0)

    def test_functions_added_or_removed_wholesale_are_excluded(self):
        before = "def a(x):\n    return x\n"
        after = "def a(x):\n    return x\n\ndef brand_new(y):\n    return helper(y)\n"
        self.assertEqual(gd.function_deltas(before, after), [],
                         "a new function has no 'before' to lose references against")


class SkippedIsNeitherPassNorFail(unittest.TestCase):
    def test_a_drifted_anchor_is_skipped_with_a_reason(self):
        class FakeMutation:
            id, defect_class, file = "fake", "logic", "daedalus/structcore/parse.py"
            find, replace = "THIS TEXT IS NOT IN THE FILE ANYWHERE", "x"

        res = gd.measure(FakeMutation(), ".")
        self.assertFalse(res.applied)
        self.assertFalse(res.detected)
        self.assertIn("drifted", res.skipped_reason)

    def test_a_missing_file_is_skipped_not_counted(self):
        class FakeMutation:
            id, defect_class, file = "fake", "logic", "does/not/exist.py"
            find, replace = "a", "b"

        res = gd.measure(FakeMutation(), ".")
        self.assertFalse(res.applied)
        self.assertIn("cannot read", res.skipped_reason)


class CorpusLoads(unittest.TestCase):
    def test_the_mutation_corpus_imports_and_is_not_empty(self):
        muts = gd.load_mutations(".")
        self.assertGreater(len(muts), 5)
        self.assertTrue(all(hasattr(m, "defect_class") for m in muts))




class LiteralLayer(unittest.TestCase):
    """The layer that closed the data-only blind spot — and its own limits."""

    def test_a_value_added_to_a_tuple_is_visible(self):
        """`FREE_LANES = (...)` gaining "claude_cli" changes no identifier at all;
        this is the exact shape of the mutation the reference layer missed."""
        before = 'FREE_LANES = ("ollama", "deepseek")\n'
        after = 'FREE_LANES = ("ollama", "deepseek", "claude_cli")\n'
        self.assertNotEqual(gd._literal_keys("m.py", after), gd._literal_keys("m.py", before))

    def test_a_dropped_argv_flag_is_visible(self):
        before = 'def f():\n    return ["git", "diff", "--no-textconv"]\n'
        after = 'def f():\n    return ["git", "diff"]\n'
        removed = gd._literal_keys("m.py", before) - gd._literal_keys("m.py", after)
        self.assertTrue(any("no-textconv" in k for k in removed))

    def test_losing_one_of_two_identical_literals_is_visible(self):
        before = 'def f():\n    return ["-v", "-v"]\n'
        after = 'def f():\n    return ["-v"]\n'
        self.assertTrue(gd._literal_keys("m.py", before) - gd._literal_keys("m.py", after))

    def test_module_level_constants_are_seen(self):
        """A module assignment is outside every function, so a function-scoped
        walk would never see FREE_LANES change."""
        keys = gd._literal_keys("m.py", 'TIMEOUT = 30\n')
        self.assertTrue(any("30" in k for k in keys))

    def test_a_long_literal_is_clipped_so_a_secret_cannot_ride_along(self):
        secret = "x" * 500
        keys = gd._literal_keys("m.py", f'def f():\n    return "{secret}"\n')
        self.assertTrue(all(len(k) < 200 for k in keys))
        self.assertFalse(any(secret in k for k in keys))

    def test_a_docstring_is_not_a_literal(self):
        before = 'def f():\n    """One."""\n    return 1\n'
        after = 'def f():\n    """Two, entirely rewritten."""\n    return 1\n'
        self.assertEqual(gd._literal_keys("m.py", before), gd._literal_keys("m.py", after))

    def test_the_literal_layer_can_score(self):
        self.assertIn("literals", gd.DeltaResult.SCORING_LAYERS)



class StructureLayer(unittest.TestCase):
    """The layer for control-flow-only edits, and its orthogonality guarantee."""

    def test_an_inserted_early_return_is_visible(self):
        """Neither names nor values change; only the shape does."""
        before = "def f(x):\n    verify(x)\n    return x\n"
        after = "def f(x):\n    return\n    verify(x)\n    return x\n"
        self.assertNotEqual(gd._structure_keys("m.py", after), gd._structure_keys("m.py", before))

    def test_an_inverted_condition_is_visible(self):
        before = "def f(x):\n    if ok(x):\n        return 1\n    return 0\n"
        after = "def f(x):\n    if not ok(x):\n        return 1\n    return 0\n"
        self.assertNotEqual(gd._structure_keys("m.py", after), gd._structure_keys("m.py", before))

    def test_it_is_orthogonal_to_names(self):
        """Renaming a variable must move references and NOT structure — that
        orthogonality is what lets the three layers be read independently."""
        before = "def f(x):\n    total = compute(x)\n    return total\n"
        after = "def f(x):\n    result = compute(x)\n    return result\n"
        self.assertEqual(gd._structure_keys("m.py", after), gd._structure_keys("m.py", before))
        self.assertNotEqual(gd._ast_refs("m.py", after)[0], gd._ast_refs("m.py", before)[0])

    def test_it_is_orthogonal_to_values(self):
        before = "def f():\n    return timeout(30)\n"
        after = "def f():\n    return timeout(60)\n"
        self.assertEqual(gd._structure_keys("m.py", after), gd._structure_keys("m.py", before))
        self.assertNotEqual(gd._literal_keys("m.py", after), gd._literal_keys("m.py", before))

    def test_a_docstring_rewrite_moves_nothing(self):
        before = 'def f():\n    """A."""\n    return 1\n'
        after = 'def f():\n    """B, at length."""\n    return 1\n'
        self.assertEqual(gd._structure_keys("m.py", after), gd._structure_keys("m.py", before))

    def test_the_structure_layer_can_score(self):
        self.assertIn("structure", gd.DeltaResult.SCORING_LAYERS)

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
