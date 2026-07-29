"""Tests for tools/mutation_score.py -- the scorer has to be falsifiable too.

The point of this file is not coverage. It is that a tool whose whole job is
"prove the suite can go red" must itself be shown to go red for the right
reasons, in both directions:

  * a module with GOOD tests scores 100% and names no survivor;
  * a module with WEAK tests yields NAMED survivors and a score below 100%;
  * and -- the control that matters -- REMOVING a covering test from the good
    module flips a previously-CAUGHT mutant to SURVIVED and drops the score.
    Without that last one, "100%" could just mean the tool cannot detect
    anything, which is the exact failure mode it exists to expose.

Plus the three rules the two hand-rolled instances (runs/ab/oracle_check.py,
tools/self_test.py) paid a round each to learn: a red baseline is not a score,
a mutation that does not apply is not a survivor, and nothing touches the
working repository.
"""
from __future__ import annotations

import ast
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import mutation_score as ms  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures -- a tiny throwaway "repo" with one well-tested and one badly        #
# tested module, so the scorer is exercised against a known answer.             #
# --------------------------------------------------------------------------- #
GOOD_MODULE = textwrap.dedent('''\
    """A module whose every branch is pinned by a test."""
    DENY = ("secret", "token")


    def is_allowed(path, size):
        if not path:
            return False
        low = path.lower()
        for d in DENY:
            if d in low:
                return False
        if size > 1024:
            return False
        return True
    ''')

GOOD_TESTS = textwrap.dedent('''\
    from goodmod import is_allowed


    def test_empty_path_denied():
        assert is_allowed("", 1) is False


    def test_secret_denied():
        assert is_allowed("a/secret.txt", 1) is False


    def test_token_denied():
        assert is_allowed("TOKEN.md", 1) is False


    def test_big_denied():
        assert is_allowed("a.txt", 2048) is False


    def test_boundary_is_allowed():
        assert is_allowed("a.txt", 1024) is True


    def test_normal_allowed():
        assert is_allowed("a.txt", 10) is True
    ''')

WEAK_MODULE = textwrap.dedent('''\
    """A module with branches nobody exercises."""


    def classify(n, strict=False):
        if n < 0:
            return "negative"
        if strict and n > 100:
            return "huge"
        if n == 0:
            return "zero"
        return "positive"
    ''')

WEAK_TESTS = textwrap.dedent('''\
    from weakmod import classify


    def test_zero():
        assert classify(0) == "zero"


    def test_positive():
        assert classify(7) == "positive"
    ''')

RED_TESTS = textwrap.dedent('''\
    from goodmod import is_allowed


    def test_that_was_already_failing():
        assert is_allowed("a.txt", 10) is False
    ''')


def build_fixture_repo(root: Path) -> None:
    (root / "goodmod.py").write_text(GOOD_MODULE, encoding="utf-8")
    (root / "weakmod.py").write_text(WEAK_MODULE, encoding="utf-8")
    tests = root / "t"
    tests.mkdir()
    (tests / "test_goodmod.py").write_text(GOOD_TESTS, encoding="utf-8")
    (tests / "test_weakmod.py").write_text(WEAK_TESTS, encoding="utf-8")
    (tests / "test_red.py").write_text(RED_TESTS, encoding="utf-8")


class _FakeRunner:
    """A runner whose verdicts are scripted, so the CLASSIFICATION logic can be
    tested without paying for a real pytest process."""

    def __init__(self, baseline: set[str], per_call: list):
        self.baseline = baseline
        self.per_call = list(per_call)
        self.calls = 0

    def __call__(self, root, test_paths, timeout):
        self.calls += 1
        if self.calls == 1:
            return ms.RunResult(returncode=0 if not self.baseline else 1,
                                failing=set(self.baseline))
        nxt = self.per_call.pop(0) if self.per_call else set()
        if nxt == "TIMEOUT":
            return ms.RunResult(returncode=-1, timed_out=True)
        failing = set(self.baseline) | set(nxt)
        return ms.RunResult(returncode=0 if not failing else 1, failing=failing)


# --------------------------------------------------------------------------- #
# the generator                                                                #
# --------------------------------------------------------------------------- #
class GeneratorTests(unittest.TestCase):
    def test_every_operator_is_reachable(self):
        src = textwrap.dedent('''\
            def f(a, b, flag=True):
                if a == b:
                    return False
                if not flag:
                    raise ValueError("x")
                if a > 0 and b > 0:
                    return True
                return flag
            ''')
        got = {m.operator for m in ms.generate_mutations(src, "f.py")}
        self.assertEqual(got, set(ms.OPERATORS),
                         f"an operator produced nothing: {set(ms.OPERATORS) - got}")

    def test_order_is_deterministic(self):
        src = GOOD_MODULE
        a = ms.generate_mutations(src, "goodmod.py")
        b = ms.generate_mutations(src, "goodmod.py")
        self.assertEqual([m.id for m in a], [m.id for m in b])
        keys = [(m.line, m.col, m.operator) for m in a]
        self.assertEqual(keys, sorted(keys), "order must not depend on ast.walk")

    def test_sample_is_spread_and_deterministic(self):
        muts = ms.generate_mutations(GOOD_MODULE, "goodmod.py")
        self.assertGreater(len(muts), 4)
        first = ms.sample(muts, 3)
        self.assertEqual([m.id for m in first], [m.id for m in ms.sample(muts, 3)])
        # spread, not a prefix: the last sampled mutant is past the first three
        self.assertGreater(first[-1].line, muts[2].line)

    def test_every_generated_mutant_compiles_and_changes_bytes(self):
        for m in ms.generate_mutations(GOOD_MODULE, "goodmod.py"):
            mutated = m.apply(GOOD_MODULE)
            self.assertIsNotNone(mutated, m.id)
            self.assertNotEqual(mutated, GOOD_MODULE, m.id)
            ast.parse(mutated)  # must still be valid Python

    def test_utf8_column_offsets(self):
        """``ast`` reports col_offset in BYTES. A non-ASCII line above the
        mutation site must not shift the edit."""
        src = 'def f(x):\n    label = "Grüße-Ärger-☃"\n    if x == 3:\n        return 1\n    return 0\n'
        cmps = [m for m in ms.generate_mutations(src, "u.py") if m.operator == "comparison"]
        self.assertEqual(len(cmps), 1)
        self.assertEqual(cmps[0].before.strip(), "==")
        self.assertIn("x != 3", cmps[0].apply(src))

    def test_unparseable_source_yields_nothing(self):
        self.assertEqual(ms.generate_mutations("def (:\n", "bad.py"), [])

    def test_guard_operator_only_targets_guards(self):
        src = textwrap.dedent('''\
            def f(x):
                if x:
                    return 1
                if x:
                    y = 2
                    return y
                if x:
                    return 3
                else:
                    return 4
            ''')
        guards = [m for m in ms.generate_mutations(src, "g.py")
                  if m.operator == "guard_never_fires"]
        # only the first `if` is a pure guard (single terminator, no else)
        self.assertEqual([m.line for m in guards], [2])


# --------------------------------------------------------------------------- #
# anchoring -- a mutation that does not apply is never a survivor              #
# --------------------------------------------------------------------------- #
class AnchorTests(unittest.TestCase):
    def test_span_mutation_refuses_when_the_file_moved_underneath(self):
        m = ms.generate_mutations(GOOD_MODULE, "goodmod.py")[0]
        shifted = "# another agent added a line\n" + GOOD_MODULE
        self.assertIsNone(m.apply(shifted),
                          "a shifted span must refuse, not land somewhere else")

    def test_patch_mutation_subsumes_the_hand_rolled_shape(self):
        m = ms.Mutation.patch("goodmod.py", "size > 1024", "size > 999999",
                              rule="the size ceiling", expect_test="test_big_denied")
        self.assertIn("size > 999999", m.apply(GOOD_MODULE))
        self.assertIsNone(ms.Mutation.patch("goodmod.py", "nope", "x").apply(GOOD_MODULE))

    def test_no_op_edit_is_not_applicable(self):
        self.assertIsNone(ms.Mutation.patch("m.py", "a", "a").apply("a = 1\n"))


# --------------------------------------------------------------------------- #
# classification, without paying for real pytest                              #
# --------------------------------------------------------------------------- #
class ClassificationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="mstest-"))
        build_fixture_repo(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_red_baseline_is_inconclusive_never_a_score(self):
        runner = _FakeRunner(baseline={"t/test_red.py::test_that_was_already_failing"},
                             per_call=[set(), set()])
        rep = ms.score(self.tmp, "goodmod.py", ["t"], n_sample=2, runner=runner)
        self.assertFalse(rep["baseline_green"])
        self.assertIsNone(rep["mutation_score"])
        self.assertEqual(rep["verdict"], ms.INCONCLUSIVE)

    def test_timeout_is_inconclusive_not_caught(self):
        runner = _FakeRunner(baseline=set(), per_call=["TIMEOUT"])
        rep = ms.score(self.tmp, "goodmod.py", ["t"], n_sample=1, runner=runner)
        self.assertEqual([r["status"] for r in rep["results"]], [ms.INCONCLUSIVE])
        self.assertEqual(rep["n_caught"], 0)
        self.assertEqual(rep["n_survived"], 0)

    def test_expect_test_requires_the_named_test_to_go_red(self):
        m = ms.Mutation.patch("goodmod.py", "size > 1024", "size > 999999",
                              rule="the size ceiling", expect_test="test_big_denied")
        # something unrelated went red -> detection by accident, not coverage
        runner = _FakeRunner(baseline=set(), per_call=[{"t/test_goodmod.py::test_other"}])
        rep = ms.score(self.tmp, "goodmod.py", ["t"], mutations=[m], runner=runner)
        self.assertEqual(rep["results"][0]["status"], ms.SURVIVED)

        runner = _FakeRunner(baseline=set(),
                             per_call=[{"t/test_goodmod.py::test_big_denied"}])
        rep = ms.score(self.tmp, "goodmod.py", ["t"], mutations=[m], runner=runner)
        self.assertEqual(rep["results"][0]["status"], ms.CAUGHT)

    def test_inapplicable_mutation_is_not_counted_as_a_survivor(self):
        m = ms.Mutation.patch("goodmod.py", "this text is not in the file", "x")
        runner = _FakeRunner(baseline=set(), per_call=[])
        rep = ms.score(self.tmp, "goodmod.py", ["t"], mutations=[m], runner=runner)
        self.assertEqual(rep["results"][0]["status"], ms.NOT_APPLICABLE)
        self.assertEqual(rep["n_survived"], 0)
        self.assertEqual(rep["n_not_applicable"], 1)
        self.assertIsNone(rep["mutation_score"], "nothing scoreable is not 100%")
        self.assertEqual(runner.calls, 1, "an inapplicable mutant must cost no test run")


# --------------------------------------------------------------------------- #
# the real thing -- an actual pytest subprocess against the fixture repo       #
# --------------------------------------------------------------------------- #
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="mse2e-"))
        build_fixture_repo(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_good_tests_kill_every_mutant(self):
        rep = ms.score(self.tmp, "goodmod.py", ["t/test_goodmod.py"], timeout=300)
        self.assertTrue(rep["baseline_green"], rep.get("baseline_output", ""))
        self.assertEqual(rep["n_survived"], 0,
                         [r for r in rep["results"] if r["status"] == ms.SURVIVED])
        self.assertEqual(rep["mutation_score"], 1.0)
        self.assertEqual(rep["verdict"], "NO_SURVIVORS")

    def test_weak_tests_leave_named_survivors(self):
        rep = ms.score(self.tmp, "weakmod.py", ["t/test_weakmod.py"], timeout=300)
        self.assertTrue(rep["baseline_green"], rep.get("baseline_output", ""))
        survivors = [r for r in rep["results"] if r["status"] == ms.SURVIVED]
        self.assertGreater(len(survivors), 0, "a suite that never calls strict= "
                                              "cannot possibly kill the strict branch")
        self.assertLess(rep["mutation_score"], 1.0)
        self.assertEqual(rep["verdict"], "SURVIVORS")
        # the survivor is NAMED, with a line number a human can act on
        self.assertTrue(all(r["line"] > 0 and r["operator"] for r in survivors))

    def test_dropping_a_covering_test_flips_a_kill_into_a_survivor(self):
        """THE control on the scorer itself. If weakening the suite does not
        move the score, the score is not measuring the suite."""
        strong = ms.score(self.tmp, "goodmod.py", ["t/test_goodmod.py"],
                          operators=("guard_never_fires",), timeout=300)
        weakened = ms.score(self.tmp, "goodmod.py", ["t/test_goodmod.py"],
                            operators=("guard_never_fires",),
                            drop_tests=("test_big_denied",), timeout=300)
        self.assertTrue(strong["baseline_green"] and weakened["baseline_green"])
        self.assertEqual(strong["n_survived"], 0)
        self.assertGreater(weakened["n_survived"], 0,
                           "removing the only test of the size ceiling must "
                           "leave that guard undetectable")
        self.assertLess(weakened["mutation_score"], strong["mutation_score"])

    def test_the_working_tree_is_never_written_to(self):
        before = {p: p.read_bytes() for p in self.tmp.rglob("*.py")}
        ms.score(self.tmp, "goodmod.py", ["t/test_goodmod.py"], n_sample=2, timeout=300)
        after = {p: p.read_bytes() for p in self.tmp.rglob("*.py")}
        self.assertEqual(before, after,
                         "a mutation run must leave the subject repository "
                         "byte-identical")

    def test_sandbox_is_destroyed(self):
        seen = {}
        real = ms.pytest_runner

        def spy(root, test_paths, timeout):
            seen["root"] = Path(root)
            return real(root, test_paths, timeout)

        ms.score(self.tmp, "goodmod.py", ["t/test_goodmod.py"], n_sample=1,
                 timeout=300, runner=spy)
        self.assertIn("root", seen)
        self.assertFalse(seen["root"].exists(), "the sandbox outlived the run")


class DropTestControlTests(unittest.TestCase):
    def test_drop_test_removes_the_function_and_still_parses(self):
        out = ms.drop_test(GOOD_TESTS, "test_big_denied")
        self.assertNotIn("test_big_denied", out)
        self.assertIn("test_normal_allowed", out)
        ast.parse(out)

    def test_drop_test_refuses_silently_doing_nothing(self):
        with self.assertRaises(ValueError):
            ms.drop_test(GOOD_TESTS, "no_such_test")


class RenderTests(unittest.TestCase):
    def test_render_states_the_limits_next_to_the_number(self):
        rep = {"schema": 1, "module": "m.py", "tests": ["t"], "dropped_tests": [],
               "operators": list(ms.OPERATORS), "n_generated": 1,
               "baseline_green": True, "baseline_failures": [], "baseline_seconds": 1.0,
               "results": [{"id": "x", "operator": "boolop", "line": 3,
                            "status": ms.SURVIVED, "rule": "the and is load-bearing",
                            "detail": "", "before": "and", "after": "or",
                            "newly_failing": [], "seconds": 1.0}],
               "n_caught": 0, "n_survived": 1, "n_not_applicable": 0,
               "n_inconclusive": 0, "mutation_score": 0.0, "verdict": "SURVIVORS"}
        text = ms.render(rep)
        self.assertIn("SURVIVED", text)
        self.assertIn("UNFALSIFIABLE", text)
        self.assertIn("equivalent mutant", text)
        self.assertIn("mutation score: 0.0%", text)


if __name__ == "__main__":
    unittest.main()
