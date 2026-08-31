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
import json
import sys
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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
        self.selections: list[tuple[str, ...]] = []
        self.timeouts: list[float | None] = []

    def __call__(self, root, test_paths, timeout):
        self.calls += 1
        self.selections.append(tuple(test_paths))
        self.timeouts.append(timeout)
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


class ExplicitSpecTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="msspec-"))
        build_fixture_repo(self.tmp)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_spec(self, *, find: str = "size > 1024") -> Path:
        path = self.tmp / "spec.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "spec_id": "fixture",
                    "packet_id": "TEST-MUT-01",
                    "jobs": [
                        {
                            "module": "goodmod.py",
                            "tests": ["t/test_goodmod.py"],
                            "timeout_s": 30,
                            "mutations": [
                                {
                                    "id": "break-size-limit",
                                    "find": find,
                                    "replace": "size > 999999",
                                    "tests": [
                                        "t/test_goodmod.py::test_big_denied"
                                    ],
                                    "expect_test": "test_big_denied",
                                    "rule": "the size limit is enforced",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_spec_loads_exact_anchored_mutations(self):
        spec = ms.load_explicit_spec(self.tmp, self._write_spec())
        self.assertEqual(spec.spec_id, "fixture")
        self.assertEqual(spec.jobs[0].module, "goodmod.py")
        self.assertEqual(spec.jobs[0].mutations[0].id, "break-size-limit")

    def test_spec_refuses_an_ambiguous_anchor(self):
        with self.assertRaisesRegex(ms.MutationSpecError, "found 3"):
            ms.load_explicit_spec(self.tmp, self._write_spec(find="return False"))

    def test_spec_refuses_paths_outside_the_repository(self):
        payload = json.loads(self._write_spec().read_text(encoding="utf-8"))
        payload["jobs"][0]["module"] = "../outside.py"
        path = self.tmp / "spec.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ms.MutationSpecError, "within the repository"):
            ms.load_explicit_spec(self.tmp, path)

    def test_mutant_test_outside_baseline_requires_an_explicit_allowlist(self):
        path = self._write_spec()
        payload = json.loads(path.read_text(encoding="utf-8"))
        selected = "t/test_weakmod.py::test_zero"
        payload["jobs"][0]["mutations"][0]["tests"] = [selected]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(
            ms.MutationSpecError,
            "absent from the job baseline and mutant_test_files",
        ):
            ms.load_explicit_spec(self.tmp, path)

        payload["jobs"][0]["mutant_test_files"] = ["t/test_weakmod.py"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        spec = ms.load_explicit_spec(self.tmp, path)
        self.assertEqual(spec.jobs[0].tests, ("t/test_goodmod.py",))
        self.assertEqual(
            spec.jobs[0].mutant_test_files,
            ("t/test_weakmod.py",),
        )
        self.assertEqual(spec.jobs[0].mutations[0].test_paths, (selected,))

    def test_mutant_test_file_allowlist_is_strict(self):
        path = self._write_spec()
        payload = json.loads(path.read_text(encoding="utf-8"))
        for value in ("t/test_weakmod.py", ["missing.py"]):
            with self.subTest(value=value):
                payload["jobs"][0]["mutant_test_files"] = value
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    ms.MutationSpecError,
                    "mutant_test_files",
                ):
                    ms.load_explicit_spec(self.tmp, path)

    def test_legacy_unbounded_timeout_is_strictly_opt_in_per_job(self):
        path = self._write_spec()
        bounded = ms.load_explicit_spec(self.tmp, path).jobs[0]
        self.assertEqual(bounded.timeout_policy, ms.JOB_TIMEOUT_BOUNDED)
        self.assertEqual(bounded.timeout_s, 30.0)

        payload = json.loads(path.read_text(encoding="utf-8"))
        job = payload["jobs"][0]
        job.pop("timeout_s")
        job["timeout_policy"] = ms.JOB_TIMEOUT_LEGACY_UNBOUNDED
        path.write_text(json.dumps(payload), encoding="utf-8")
        unbounded_spec = ms.load_explicit_spec(self.tmp, path)
        unbounded = unbounded_spec.jobs[0]
        self.assertEqual(
            unbounded.timeout_policy,
            ms.JOB_TIMEOUT_LEGACY_UNBOUNDED,
        )
        self.assertIsNone(unbounded.timeout_s)

        runner = _FakeRunner(
            baseline=set(),
            per_call=[{"t/test_goodmod.py::test_big_denied"}],
        )
        report = ms.score_explicit_spec(
            self.tmp,
            unbounded_spec,
            runner=runner,
        )
        self.assertEqual(report["verdict"], "NO_SURVIVORS")
        self.assertEqual(ms._explicit_spec_exit_code(unbounded_spec, report), 0)
        self.assertEqual(
            runner.selections,
            [("t/test_goodmod.py",), ("t/test_goodmod.py::test_big_denied",)],
        )
        self.assertEqual(runner.timeouts, [None, None])

        survivor_runner = _FakeRunner(baseline=set(), per_call=[set()])
        survivor_report = ms.score_explicit_spec(
            self.tmp,
            unbounded_spec,
            runner=survivor_runner,
        )
        self.assertEqual(survivor_report["verdict"], "SURVIVORS")
        self.assertEqual(
            ms._explicit_spec_exit_code(unbounded_spec, survivor_report),
            1,
        )

        red_runner = _FakeRunner(
            baseline={"t/test_goodmod.py::already_red"},
            per_call=[set()],
        )
        red_report = ms.score_explicit_spec(
            self.tmp,
            unbounded_spec,
            runner=red_runner,
        )
        self.assertEqual(red_report["verdict"], ms.INCONCLUSIVE)
        self.assertEqual(
            ms._explicit_spec_exit_code(unbounded_spec, red_report),
            2,
        )

    def test_legacy_unbounded_timeout_refuses_conflicts_and_unknown_values(self):
        for timeout_policy, timeout_present in (
            ("unbounded", False),
            (ms.JOB_TIMEOUT_LEGACY_UNBOUNDED, True),
            (None, False),
        ):
            with self.subTest(
                timeout_policy=timeout_policy,
                timeout_present=timeout_present,
            ):
                path = self._write_spec()
                payload = json.loads(path.read_text(encoding="utf-8"))
                job = payload["jobs"][0]
                if not timeout_present:
                    job.pop("timeout_s")
                job["timeout_policy"] = timeout_policy
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    ms.MutationSpecError,
                    "timeout_policy|must be omitted",
                ):
                    ms.load_explicit_spec(self.tmp, path)

    def test_spec_refuses_unknown_mutant_timeout_policy(self):
        for value in ("credit-timeout-as-kill", ["legacy-timeout-exit-1"]):
            with self.subTest(value=value):
                path = self._write_spec()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["mutant_timeout_policy"] = value
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    ms.MutationSpecError,
                    "mutant_timeout_policy",
                ):
                    ms.load_explicit_spec(self.tmp, path)

    def test_legacy_mutant_timeout_policy_preserves_text_and_exit_one(self):
        path = self._write_spec()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["mutant_timeout_policy"] = ms.MUTANT_TIMEOUT_LEGACY_EXIT_1
        path.write_text(json.dumps(payload), encoding="utf-8")
        spec = ms.load_explicit_spec(self.tmp, path)
        report = ms.score_explicit_spec(
            self.tmp,
            spec,
            runner=_FakeRunner(baseline=set(), per_call=["TIMEOUT"]),
        )
        self.assertEqual(report["verdict"], ms.INCONCLUSIVE)
        self.assertEqual(report["timed_out_mutations"], ["break-size-limit"])
        self.assertEqual(ms._explicit_spec_exit_code(spec, report), 1)
        self.assertEqual(
            ms._legacy_timeout_summary(report),
            "timed-out mutations: break-size-limit",
        )
        import contextlib
        import io

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "daedalus.budget.process_guard_boundary_decision",
                return_value=object(),
            ),
            mock.patch("daedalus.spine.effect_boundary.begin_effect"),
            mock.patch.object(ms, "score_explicit_spec", return_value=report),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = ms.main(
                ["--repo", str(self.tmp), "--spec", str(path)]
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.getvalue(),
            "timed-out mutations: break-size-limit\n",
        )
        self.assertIn("INCONCLUSIVE", stdout.getvalue())
        self.assertEqual(
            ms._explicit_spec_exit_code(
                spec,
                {**report, "baseline_green": False},
            ),
            2,
        )
        self.assertEqual(
            ms._explicit_spec_exit_code(
                spec,
                {**report, "n_inconclusive": 2},
            ),
            2,
        )

    def test_default_mutant_timeout_policy_remains_exit_two(self):
        spec = ms.load_explicit_spec(self.tmp, self._write_spec())
        report = ms.score_explicit_spec(
            self.tmp,
            spec,
            runner=_FakeRunner(baseline=set(), per_call=["TIMEOUT"]),
        )
        self.assertEqual(
            spec.mutant_timeout_policy,
            ms.MUTANT_TIMEOUT_INCONCLUSIVE,
        )
        self.assertEqual(ms._explicit_spec_exit_code(spec, report), 2)

    def test_spec_scoring_requires_the_named_test_to_kill_the_mutant(self):
        spec = ms.load_explicit_spec(self.tmp, self._write_spec())
        runner = _FakeRunner(
            baseline=set(),
            per_call=[{"t/test_goodmod.py::test_big_denied"}],
        )
        report = ms.score_explicit_spec(self.tmp, spec, runner=runner)
        self.assertEqual(report["verdict"], "NO_SURVIVORS")
        self.assertEqual(report["n_caught"], 1)
        self.assertEqual(report["n_survived"], 0)
        self.assertEqual(runner.selections[0], ("t/test_goodmod.py",))
        self.assertEqual(
            runner.selections[1],
            ("t/test_goodmod.py::test_big_denied",),
        )

    def test_spec_list_mode_is_read_only_and_does_not_score(self):
        path = self._write_spec()
        before = {item: item.read_bytes() for item in self.tmp.rglob("*") if item.is_file()}
        self.assertEqual(
            ms.main(["--repo", str(self.tmp), "--spec", str(path), "--list"]),
            0,
        )
        after = {item: item.read_bytes() for item in self.tmp.rglob("*") if item.is_file()}
        self.assertEqual(before, after)

    def test_repository_tree_wrapper_is_a_thin_spec_caller(self):
        root = Path(__file__).resolve().parents[1]
        spec = ms.load_explicit_spec(
            root,
            root / "configs/mutations/repository-tree.json",
        )
        self.assertEqual(spec.packet_id, "G1-MUT-01")
        self.assertEqual(len(spec.jobs), 1)
        self.assertEqual(len(spec.jobs[0].mutations), 8)
        wrapper = (root / "scripts/run_repository_tree_mutations.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("tools.mutation_score", wrapper)
        self.assertIn("repository-tree.json", wrapper)
        self.assertNotIn("write_text", wrapper)
        self.assertNotIn("subprocess", wrapper)


# --------------------------------------------------------------------------- #
# reading the runner's output -- a coloured FAILED is still a failure          #
# --------------------------------------------------------------------------- #
class OutputParsingTests(unittest.TestCase):
    """RED-VERIFIED against the pre-fix runner: with FORCE_COLOR set (this agent
    environment exports FORCE_COLOR=3), pytest wraps its summary in SGR codes,
    ``_FAIL_RE``'s ``^`` anchor missed every one, and each KILLED mutant was
    filed as INCONCLUSIVE -- leaving `mutation_score` None for a suite that was
    in fact killing everything. The scorer silently measured nothing."""

    COLOURED = (
        "\x1b[31mFAILED\x1b[0m t/test_goodmod.py::\x1b[1mtest_big_denied\x1b[0m"
        " - AssertionError: assert True is False\n"
        "\x1b[31mERROR\x1b[0m t/test_other.py::\x1b[1mtest_boom\x1b[0m\n"
        "\x1b[31m\x1b[1m1 failed\x1b[0m, \x1b[32m5 passed\x1b[0m in 0.64s\n"
    )

    def test_ansi_is_stripped_before_the_summary_is_parsed(self):
        plain = ms._strip_ansi(self.COLOURED)
        self.assertNotIn("\x1b", plain)
        failing = {m.group(1) for line in plain.splitlines()
                   if (m := ms._FAIL_RE.match(line.strip()))}
        self.assertEqual(failing, {"t/test_goodmod.py::test_big_denied",
                                   "t/test_other.py::test_boom"})

    def test_the_raw_coloured_form_is_what_defeated_the_parse(self):
        """The control: without the strip, the same input yields NOTHING. If
        this ever starts matching, the bug this guards has changed shape."""
        failing = {m.group(1) for line in self.COLOURED.splitlines()
                   if (m := ms._FAIL_RE.match(line.strip()))}
        self.assertEqual(failing, set())

    def test_plain_output_is_unchanged_by_the_strip(self):
        plain = "FAILED t/test_x.py::test_y - boom\n1 failed in 0.1s\n"
        self.assertEqual(ms._strip_ansi(plain), plain)

    def test_the_runner_disables_colour_at_the_source(self):
        """Stripping is the second line of defence; not asking for colour is the
        first. Pinned so a future edit cannot drop it and rely on the strip."""
        import inspect
        self.assertIn('"--color=no"', inspect.getsource(ms.pytest_runner))

    def test_the_runner_refuses_bytecode_and_external_plugins(self):
        """Equal-length mutants must not reuse a previous subprocess' pyc.

        The repository-tree shadow exposed this on Windows: several explicit
        guard deletions add the same number of bytes, so timestamp/size based
        bytecode validation could execute the preceding mutant instead.
        """
        completed = SimpleNamespace(returncode=0, stdout="1 passed\n", stderr="")
        with mock.patch.object(ms.subprocess, "run", return_value=completed) as run:
            result = ms.pytest_runner(Path("."), ["t/test_x.py"], 1)
        self.assertTrue(result.green)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
        self.assertEqual(run.call_args.kwargs["timeout"], 1)

    def test_the_runner_omits_the_subprocess_deadline_only_when_opted_out(self):
        completed = SimpleNamespace(returncode=0, stdout="1 passed\n", stderr="")
        with mock.patch.object(ms.subprocess, "run", return_value=completed) as run:
            result = ms.pytest_runner(Path("."), ["t/test_x.py"], None)
        self.assertTrue(result.green)
        self.assertNotIn("timeout", run.call_args.kwargs)


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

    def test_expected_test_runner_error_is_inconclusive_not_a_survivor(self):
        m = ms.Mutation.patch(
            "goodmod.py",
            "size > 1024",
            "size > 999999",
            rule="the size ceiling",
            expect_test="test_big_denied",
        )

        def runner(root, test_paths, timeout):
            if test_paths == ["t"]:
                return ms.RunResult(returncode=0)
            return ms.RunResult(returncode=4, output="node not found")

        m = ms.Mutation.patch(
            m.rel_path,
            m.before,
            m.after,
            rule=m.rule,
            expect_test=m.expect_test,
            test_paths=("t/test_goodmod.py::missing",),
        )
        rep = ms.score(self.tmp, "goodmod.py", ["t"], mutations=[m], runner=runner)
        self.assertEqual(rep["results"][0]["status"], ms.INCONCLUSIVE)
        self.assertEqual(rep["n_survived"], 0)

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
