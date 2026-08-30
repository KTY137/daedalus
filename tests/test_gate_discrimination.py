# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""tools/gate_discrimination.py -- the corpus mechanics, not the real measurement.

The real measurement (clone the working tree, seed 11 real defects, run the
whole pytest suite once per defect) takes on the order of an hour and is
invoked by hand as ``python tools/gate_discrimination.py`` -- it is
deliberately NOT part of this file, because ``python -m unittest discover
tests`` must stay fast and deterministic. Every external effect here is
FAKE: no real git clone (``FakeSandbox`` is a plain temp directory), and
where a real pytest subprocess *is* used (``test_default_gate_runner_*``)
it is a two-line, sub-second fixture -- never the multi-thousand-test suite,
never Ollama, never Claude, never a real device path.

Two tests literally DISABLE a guard in the tool's own source (by the same
find/replace technique the tool applies to the corpus) and prove the
behaviour it exists to prevent actually happens without it -- the standing
instruction this crew works under: "verified by ACTUALLY disabling it."
"""
from __future__ import annotations

import subprocess
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import gate_discrimination as gd  # noqa: E402
from daedalus.spine.bootstrap import (  # noqa: E402
    CRITICAL_DEFECT_CLASSES,
    KILL_RATE_FLOOR,
    gate_discrimination as bootstrap_verdict,
)


# --------------------------------------------------------------------------- #
# fakes -- no git, no real pytest suite, no network                            #
# --------------------------------------------------------------------------- #
class FakeSandbox:
    """Stand-in for system_check.Sandbox: a plain temp dir, no git at all."""

    def __init__(self, files: dict[str, str], head: str = "f" * 40,
                build_ok: bool = True):
        self._files = files
        self._head = head
        self._build_ok = build_ok
        self.error: str | None = None
        self.repo: Path | None = None
        self._tmp: TemporaryDirectory | None = None

    def build(self) -> bool:
        if not self._build_ok:
            self.error = "forced sandbox failure"
            return False
        self._tmp = TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        for rel, content in self._files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return True

    def head(self) -> str:
        return self._head

    def destroy(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


def _load_patched_module(disabled_src: str, name: str) -> types.ModuleType:
    """Exec a modified copy of the tool's own source as a REAL module object.

    ``@dataclass`` (this file uses ``from __future__ import annotations``,
    so every field annotation is a string) resolves annotations via
    ``sys.modules[cls.__module__]``, so a bare ``exec(..., ns)`` into a plain
    dict fails with an unhelpful AttributeError -- the class has to live in
    something actually registered in ``sys.modules``. Removed again after
    the caller is done with it, so a "guard disabled" test can never leak
    into another test's import of the real module.
    """
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / "tools" / "gate_discrimination.py")
    sys.modules[name] = mod
    exec(compile(disabled_src, name, "exec"), mod.__dict__)
    return mod


def scripted_gate_runner(outcomes: list):
    """First call answers the baseline; each call after answers one mutant."""
    it = iter(outcomes)

    def _runner(repo, paths, timeout_s):
        passed = next(it)
        return passed, (0 if passed else 1), "fake gate output"

    return _runner


# --------------------------------------------------------------------------- #
# corpus design invariants -- static, fast                                     #
# --------------------------------------------------------------------------- #
class CorpusDesignTests(unittest.TestCase):

    def test_every_critical_defect_class_has_at_least_one_mutation(self):
        covered = {m.defect_class for m in gd.MUTATIONS}
        missing = [c for c in CRITICAL_DEFECT_CLASSES if c not in covered]
        self.assertEqual(missing, [],
                         f"CRITICAL_DEFECT_CLASSES with no corpus entry: {missing}")

    def test_mutation_ids_are_unique(self):
        ids = [m.id for m in gd.MUTATIONS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate mutation id")

    def test_frozen_argv_is_built_by_the_real_production_function(self):
        """Pin fidelity: the tool must measure THE gate, not a lookalike."""
        from daedalus.spine.attempt import pytest_gate_argv
        self.assertEqual(gd.frozen_argv(), pytest_gate_argv(gd.FROZEN_GATE_PATHS))

    def test_frozen_gate_paths_is_the_whole_suite(self):
        # The production default every live candidate carries
        # (docs/adrs/016-autonomy-preconditions.md, P3). A narrower value here
        # would silently stop measuring the gate bootstrap.py actually runs.
        self.assertEqual(gd.FROZEN_GATE_PATHS, ())

    def test_anchors_are_present_and_unique_in_the_current_tree(self):
        rows = gd.check_anchors(ROOT)
        bad = [r for r in rows if not r["ok"]]
        self.assertEqual(bad, [], f"drifted mutation anchors: {bad}")

    def test_noncritical_and_critical_class_names_never_collide(self):
        self.assertEqual(
            set(gd.NONCRITICAL_DEFECT_CLASSES) & set(CRITICAL_DEFECT_CLASSES),
            set())


# --------------------------------------------------------------------------- #
# apply / restore mechanics                                                    #
# --------------------------------------------------------------------------- #
class ApplyMutationTests(unittest.TestCase):

    def test_raises_on_missing_anchor(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "f.py").write_text("nothing to see here\n", encoding="utf-8")
            mut = gd.Mutation("x", "logic", "f.py", "NOT_PRESENT", "REPLACED", "test")
            with self.assertRaises(LookupError):
                gd.apply_mutation(repo, mut)

    def test_raises_on_duplicate_anchor(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "f.py").write_text("dup\ndup\n", encoding="utf-8")
            mut = gd.Mutation("x", "logic", "f.py", "dup", "DUP", "test")
            with self.assertRaises(LookupError):
                gd.apply_mutation(repo, mut)

    def test_apply_then_restore_is_byte_identical_to_the_original(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            original = "before\nTARGET\nafter\n"
            (repo / "f.py").write_text(original, encoding="utf-8")
            mut = gd.Mutation("x", "logic", "f.py", "TARGET", "MUTATED", "test")
            saved = gd.apply_mutation(repo, mut)
            self.assertEqual(saved, original)
            self.assertIn("MUTATED", (repo / "f.py").read_text(encoding="utf-8"))
            gd.restore_mutation(repo, mut, saved)
            self.assertEqual((repo / "f.py").read_text(encoding="utf-8"), original)

    def test_disabling_the_uniqueness_guard_lets_a_duplicate_anchor_apply_silently(self):
        """Disable validate_unique_anchor's call site and show the failure mode
        it exists to prevent: a duplicate anchor gets "mutated" anyway, into
        whichever occurrence str.replace happens to find first -- which may
        not be the one the incident note describes.
        """
        src = (ROOT / "tools" / "gate_discrimination.py").read_text(encoding="utf-8")
        anchor = "    validate_unique_anchor(text, mut.find)\n"
        self.assertIn(anchor, src,
                     "the guard call site moved; update this test's anchor")
        disabled_src = src.replace(anchor, "    pass  # test-disabled\n", 1)
        try:
            mod = _load_patched_module(disabled_src, "gate_discrimination_guard_disabled")
            with TemporaryDirectory() as tmp:
                repo = Path(tmp)
                (repo / "f.py").write_text("dup\ndup\n", encoding="utf-8")
                mut = mod.Mutation("x", "logic", "f.py", "dup", "DUP", "test")
                # With the guard intact this raises (proven above). With it
                # disabled it must NOT raise, which is exactly the danger.
                mod.apply_mutation(repo, mut)
                self.assertEqual((repo / "f.py").read_text(encoding="utf-8"),
                                 "DUP\ndup\n")
        finally:
            sys.modules.pop("gate_discrimination_guard_disabled", None)


# --------------------------------------------------------------------------- #
# run_corpus orchestration                                                     #
# --------------------------------------------------------------------------- #
class RunCorpusTests(unittest.TestCase):

    def _files_for(self, mut_id: str) -> dict:
        mut = next(m for m in gd.MUTATIONS if m.id == mut_id)
        return {mut.file: f"before\n{mut.find}\nafter\n"}, mut

    def test_sandbox_build_failure_is_reported_not_swallowed(self):
        result = gd.run_corpus(
            gate_runner=scripted_gate_runner([True]),
            sandbox_factory=lambda: FakeSandbox({}, build_ok=False))
        self.assertEqual(result["state"], "sandbox_failed")
        self.assertIn("forced", result["error"])

    def test_red_baseline_aborts_before_any_mutant_is_scored(self):
        files, mut = self._files_for("attempt_reap_unwired")
        result = gd.run_corpus(
            only=mut.id,
            gate_runner=scripted_gate_runner([False]),   # baseline FAILS
            sandbox_factory=lambda: FakeSandbox(files))
        self.assertEqual(result["state"], "baseline_red")
        self.assertNotIn("results", result)

    def test_disabling_the_baseline_guard_lets_a_red_baseline_produce_a_receipt(self):
        """Same technique as the anchor-uniqueness test, aimed at the OTHER
        guard: a red baseline must never be allowed to produce a "measured"
        receipt, because every "went red" reading after it would be
        meaningless. Prove that by actually removing the check.
        """
        src = (ROOT / "tools" / "gate_discrimination.py").read_text(encoding="utf-8")
        anchor = (
            '        if not b_passed:\n'
            '            return {"state": "baseline_red", "frozen_gate": frozen,\n'
        )
        self.assertIn(anchor, src,
                     "the baseline guard moved; update this test's anchor")
        disabled_src = src.replace(
            anchor,
            '        if False:  # test-disabled\n'
            '            return {"state": "baseline_red", "frozen_gate": frozen,\n',
            1)
        try:
            mod = _load_patched_module(disabled_src, "gate_discrimination_baseline_disabled")
            files, mut = self._files_for("attempt_reap_unwired")
            result = mod.run_corpus(
                only=mut.id,
                gate_runner=scripted_gate_runner([False, True]),  # baseline FAILS, mutant "passes"
                sandbox_factory=lambda: FakeSandbox(files))
            # With the guard intact this is "baseline_red" (proven above). With
            # it disabled it proceeds to a bogus "measured" state -- the danger.
            self.assertEqual(result["state"], "measured")
        finally:
            sys.modules.pop("gate_discrimination_baseline_disabled", None)

    def test_a_caught_mutant_is_scored_correctly_and_reverted(self):
        files, mut = self._files_for("attempt_reap_unwired")
        boxes = []

        def factory():
            sb = FakeSandbox(files)
            boxes.append(sb)
            return sb

        result = gd.run_corpus(
            only=mut.id,
            gate_runner=scripted_gate_runner([True, False]),  # baseline OK, mutant CAUGHT
            sandbox_factory=factory, keep_sandbox=True)
        try:
            self.assertEqual(result["state"], "measured")
            self.assertEqual(result["planted"], 1)
            self.assertEqual(result["killed"], 1)
            self.assertEqual(result["surviving_classes"], [])
            self.assertEqual(result["results"][0]["status"], gd.STATUS_CAUGHT)
            # reverted: the sandbox file must be back to its original content
            self.assertEqual(
                boxes[0].repo.joinpath(mut.file).read_text(encoding="utf-8"),
                files[mut.file])
        finally:
            boxes[0].destroy()

    def test_a_surviving_mutant_names_its_defect_class(self):
        files, mut = self._files_for("attempt_reap_unwired")
        result = gd.run_corpus(
            only=mut.id,
            gate_runner=scripted_gate_runner([True, True]),  # baseline OK, mutant SURVIVES
            sandbox_factory=lambda: FakeSandbox(files))
        self.assertEqual(result["planted"], 1)
        self.assertEqual(result["killed"], 0)
        self.assertEqual(result["surviving_classes"], [mut.defect_class])
        self.assertEqual(result["results"][0]["status"], gd.STATUS_SURVIVED)

    def test_a_missing_anchor_is_not_applicable_not_a_survivor(self):
        mut = next(m for m in gd.MUTATIONS if m.id == "attempt_reap_unwired")
        files = {mut.file: "this file does not contain the anchor at all\n"}
        result = gd.run_corpus(
            only=mut.id,
            gate_runner=scripted_gate_runner([True]),  # only the baseline is consulted
            sandbox_factory=lambda: FakeSandbox(files))
        self.assertEqual(result["planted"], 0)
        self.assertEqual(result["killed"], 0)
        self.assertEqual(result["surviving_classes"], [])
        self.assertEqual(result["excluded"][0]["status"], gd.STATUS_NOT_APPLICABLE)

    def test_only_filter_narrows_by_id_or_class(self):
        self.assertEqual(len(gd._mutation_by_filter("worktree")), 2)
        self.assertEqual(
            len(gd._mutation_by_filter("deletes-outside-the-worktree")), 2)
        self.assertEqual(len(gd._mutation_by_filter(None)), len(gd.MUTATIONS))


# --------------------------------------------------------------------------- #
# the real (fast) gate runner, and the receipt/bootstrap contract              #
# --------------------------------------------------------------------------- #
class HeadOnlySandboxTests(unittest.TestCase):
    """Proves the thing HeadOnlySandbox exists for: an uncommitted change in
    the source repo must NOT appear in the clone. Uses a throwaway two-commit
    git repo, never this repository, never a network call.
    """

    def _git(self, *args, cwd):
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"git {args} failed: {proc.stderr}")
        return proc.stdout

    def test_uncommitted_changes_are_not_carried_into_the_clone(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            self._git("init", "-q", cwd=src)
            self._git("config", "user.email", "t@example.com", cwd=src)
            self._git("config", "user.name", "t", cwd=src)
            (src / "f.txt").write_text("committed\n", encoding="utf-8")
            self._git("add", "f.txt", cwd=src)
            self._git("commit", "-q", "-m", "initial", cwd=src)
            committed_head = self._git("rev-parse", "HEAD", cwd=src).strip()

            # Simulate another agent's in-flight, uncommitted edit.
            (src / "f.txt").write_text("UNCOMMITTED FROM ANOTHER AGENT\n",
                                       encoding="utf-8")
            (src / "untracked.txt").write_text("also not committed\n",
                                                encoding="utf-8")

            sb = gd.HeadOnlySandbox(repo_root=src)
            try:
                self.assertTrue(sb.build(), sb.error)
                self.assertEqual(sb.head(), committed_head)
                self.assertEqual((sb.repo / "f.txt").read_text(encoding="utf-8"),
                                 "committed\n")
                self.assertFalse((sb.repo / "untracked.txt").exists())
            finally:
                sb.destroy()


class DefaultGateRunnerTests(unittest.TestCase):
    """Sub-second, real pytest subprocess against a two-line throwaway fixture
    -- proves the scorer reads the subprocess return code correctly. This is
    not the corpus run; it never touches this repository's own suite.
    """

    def test_distinguishes_a_passing_and_a_failing_run(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = repo / "test_trivial.py"
            target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            passed, rc, _tail = gd._default_gate_runner(repo, (), timeout_s=60)
            self.assertTrue(passed)
            self.assertEqual(rc, 0)

            target.write_text("def test_bad():\n    assert False\n", encoding="utf-8")
            passed, rc, _tail = gd._default_gate_runner(repo, (), timeout_s=60)
            self.assertFalse(passed)
            self.assertNotEqual(rc, 0)


class ReceiptBootstrapContractTests(unittest.TestCase):
    """The scorer (this file's fakes) and the gate (bootstrap.py, UNTOUCHED
    and imported for real) must agree independently -- these tests feed a
    hand-built receipt to the REAL gate_discrimination(), never a
    reimplementation of its rules.
    """

    def test_a_clean_receipt_is_proven(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            receipt = {
                "head": "a" * 40, "measured_at": "2026-07-29T00:00:00+00:00",
                "planted": 11, "killed": 10, "surviving_classes": ["logic"],
            }
            gd.write_receipt(receipt, repo / "runs" / "spine" / "gate_discrimination.json")
            verdict = bootstrap_verdict(repo, head="a" * 40)
            self.assertTrue(verdict.proven, verdict.reason)

    def test_a_critical_survivor_blocks_proof_even_at_a_high_kill_rate(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            receipt = {
                "head": "a" * 40, "measured_at": "2026-07-29T00:00:00+00:00",
                "planted": 20, "killed": 19,
                "surviving_classes": [CRITICAL_DEFECT_CLASSES[0]],
            }
            gd.write_receipt(receipt, repo / "runs" / "spine" / "gate_discrimination.json")
            verdict = bootstrap_verdict(repo, head="a" * 40)
            self.assertFalse(verdict.proven)
            self.assertIn(CRITICAL_DEFECT_CLASSES[0], verdict.reason)

    def test_kill_rate_below_the_floor_blocks_proof(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            planted = 10
            killed = int(planted * KILL_RATE_FLOOR) - 1
            receipt = {
                "head": "a" * 40, "measured_at": "2026-07-29T00:00:00+00:00",
                "planted": planted, "killed": killed, "surviving_classes": ["boundary"],
            }
            gd.write_receipt(receipt, repo / "runs" / "spine" / "gate_discrimination.json")
            verdict = bootstrap_verdict(repo, head="a" * 40)
            self.assertFalse(verdict.proven)

    def test_receipt_for_the_wrong_revision_is_not_evidence(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            receipt = {
                "head": "a" * 40, "measured_at": "2026-07-29T00:00:00+00:00",
                "planted": 11, "killed": 11, "surviving_classes": [],
            }
            gd.write_receipt(receipt, repo / "runs" / "spine" / "gate_discrimination.json")
            verdict = bootstrap_verdict(repo, head="b" * 40)
            self.assertFalse(verdict.proven)


# --------------------------------------------------------------------------- #
# coverage-guided mutant selection (docs/ABSORPTION.md I4) -- fast, no real   #
# coverage.py run except in the one class marked REAL below.                  #
# --------------------------------------------------------------------------- #
class AnchorLinesTests(unittest.TestCase):

    def test_single_line_anchor(self):
        text = "a\nb\nTARGET\nc\n"
        self.assertEqual(gd._anchor_lines(text, "TARGET"), {3})

    def test_multi_line_anchor_spans_every_line_it_covers(self):
        text = "a\nSTART\nMID\nEND\nz\n"
        self.assertEqual(gd._anchor_lines(text, "START\nMID\nEND"), {2, 3, 4})

    def test_absent_anchor_is_the_empty_set(self):
        self.assertEqual(gd._anchor_lines("a\nb\nc\n", "NOPE"), set())

    def test_only_the_first_occurrence_is_measured(self):
        # Mirrors str.replace(..., 1) / apply_mutation's first-occurrence rule.
        text = "DUP\nx\nDUP\n"
        self.assertEqual(gd._anchor_lines(text, "DUP"), {1})


class FilterByCoverageTests(unittest.TestCase):

    def _mut(self, mut_id="m1", file="f.py", find="TARGET"):
        return gd.Mutation(mut_id, "logic", file, find, "MUTATED", "incident")

    def test_coverage_none_returns_every_mutation_unfiltered(self):
        muts = (self._mut(),)
        applicable, skipped = gd.filter_by_coverage(Path("."), muts, None)
        self.assertEqual(applicable, muts)
        self.assertEqual(skipped, [])

    def test_uncovered_anchor_is_skipped_and_named(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "f.py").write_text("before\nTARGET\nafter\n", encoding="utf-8")
            mut = self._mut()
            # Line 2 (the anchor) is NOT in the covered set for f.py.
            applicable, skipped = gd.filter_by_coverage(
                repo, (mut,), {"f.py": {1, 3}})
            self.assertEqual(applicable, ())
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["status"], gd.STATUS_UNCOVERED)
            self.assertEqual(skipped[0]["id"], "m1")
            self.assertIn("not executed", skipped[0]["detail"])

    def test_covered_anchor_stays_applicable(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "f.py").write_text("before\nTARGET\nafter\n", encoding="utf-8")
            mut = self._mut()
            applicable, skipped = gd.filter_by_coverage(
                repo, (mut,), {"f.py": {2}})
            self.assertEqual(applicable, (mut,))
            self.assertEqual(skipped, [])

    def test_backslash_and_forward_slash_paths_are_the_same_key(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "sub").mkdir()
            (repo / "sub" / "f.py").write_text("TARGET\n", encoding="utf-8")
            mut = self._mut(file="sub/f.py")
            applicable, skipped = gd.filter_by_coverage(
                repo, (mut,), {"sub\\f.py": {1}})   # coverage.py's own Windows spelling
            self.assertEqual(applicable, (mut,))
            self.assertEqual(skipped, [])

    def test_missing_anchor_is_left_applicable_for_apply_mutation_to_judge(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "f.py").write_text("no such anchor here\n", encoding="utf-8")
            mut = self._mut()
            applicable, skipped = gd.filter_by_coverage(repo, (mut,), {"f.py": set()})
            self.assertEqual(applicable, (mut,))
            self.assertEqual(skipped, [])

    def test_unreadable_file_is_left_applicable(self):
        mut = self._mut(file="does/not/exist.py")
        applicable, skipped = gd.filter_by_coverage(
            Path("."), (mut,), {"does/not/exist.py": set()})
        self.assertEqual(applicable, (mut,))
        self.assertEqual(skipped, [])


class SortByDiffRelevanceTests(unittest.TestCase):

    def _mut(self, mut_id, file):
        return gd.Mutation(mut_id, "logic", file, "x", "y", "incident")

    def test_touched_files_come_first_and_nothing_is_dropped(self):
        a = self._mut("a", "untouched.py")
        b = self._mut("b", "touched.py")
        c = self._mut("c", "also_untouched.py")
        ordered = gd.sort_by_diff_relevance((a, b, c), frozenset({"touched.py"}))
        self.assertEqual([m.id for m in ordered], ["b", "a", "c"])
        self.assertEqual(set(ordered), {a, b, c})

    def test_no_touched_files_preserves_original_order(self):
        a = self._mut("a", "x.py")
        b = self._mut("b", "y.py")
        ordered = gd.sort_by_diff_relevance((a, b), frozenset())
        self.assertEqual([m.id for m in ordered], ["a", "b"])

    def test_backslash_touched_path_matches_forward_slash_mutation_file(self):
        a = self._mut("a", "sub/f.py")
        ordered = gd.sort_by_diff_relevance((a,), frozenset({"sub\\f.py"}))
        self.assertEqual([m.id for m in ordered], ["a"])


class DiffTouchedFilesTests(unittest.TestCase):
    """Real, throwaway two-commit git repo -- same style as HeadOnlySandboxTests.
    Never this repository, never a network call."""

    def _git(self, *args, cwd):
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, f"git {args} failed: {proc.stderr}")
        return proc.stdout

    def test_names_files_changed_since_a_ref(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git("init", "-q", cwd=repo)
            self._git("config", "user.email", "t@example.com", cwd=repo)
            self._git("config", "user.name", "t", cwd=repo)
            (repo / "a.py").write_text("1\n", encoding="utf-8")
            self._git("add", "a.py", cwd=repo)
            self._git("commit", "-q", "-m", "first", cwd=repo)
            base = self._git("rev-parse", "HEAD", cwd=repo).strip()

            (repo / "b.py").write_text("2\n", encoding="utf-8")
            self._git("add", "b.py", cwd=repo)
            self._git("commit", "-q", "-m", "second", cwd=repo)

            touched = gd.diff_touched_files(repo, base)
            self.assertEqual(touched, frozenset({"b.py"}))

    def test_a_bad_ref_returns_none_not_empty(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git("init", "-q", cwd=repo)
            touched = gd.diff_touched_files(repo, "not-a-real-ref")
            self.assertIsNone(touched)


class CoveredLinesUnavailableTests(unittest.TestCase):
    """The degrade-gracefully path -- forces _coverage_available() False so
    this never depends on whether `coverage` happens to be installed."""

    def test_none_when_coverage_is_not_available(self):
        original = gd._coverage_available
        gd._coverage_available = lambda: False
        try:
            result = gd.covered_lines(Path("."), (), timeout_s=5)
        finally:
            gd._coverage_available = original
        self.assertIsNone(result)


class CoveredLinesRealTests(unittest.TestCase):
    """REAL coverage.py + REAL pytest, on a two-line throwaway fixture --
    sub-second, never this repository's own suite. Same shape as
    DefaultGateRunnerTests below: prove the subprocess/JSON plumbing actually
    works rather than trusting a mock of it. Skipped (not failed) if
    `coverage` is genuinely absent from this interpreter.
    """

    @classmethod
    def setUpClass(cls):
        if not gd._coverage_available():
            raise unittest.SkipTest("coverage.py is not installed in this interpreter")

    def test_covered_and_uncovered_lines_are_distinguished(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "sub").mkdir()
            (repo / "sub" / "__init__.py").write_text("", encoding="utf-8")
            (repo / "sub" / "mod.py").write_text(
                "def covered_fn(x):\n"
                "    return x + 1\n"
                "\n"
                "def uncovered_fn(x):\n"
                "    return x * 2\n",
                encoding="utf-8")
            (repo / "test_mod.py").write_text(
                "from sub.mod import covered_fn\n"
                "def test_it():\n"
                "    assert covered_fn(1) == 2\n",
                encoding="utf-8")
            covered = gd.covered_lines(repo, (), timeout_s=60)
            self.assertIsNotNone(covered)
            mod_covered = covered.get("sub/mod.py", set())
            self.assertIn(2, mod_covered)          # covered_fn's body ran
            self.assertNotIn(5, mod_covered)       # uncovered_fn's body never ran

    def test_end_to_end_run_corpus_skips_a_provably_uncovered_mutation(self):
        """The exact scenario I4 describes: a mutant on a line no test in the
        selection executes is a guaranteed survivor. Build a tiny corpus with
        one covered and one uncovered mutation and confirm coverage_guided=True
        skips only the uncovered one, WITHOUT ever invoking the (scripted, fast)
        gate_runner for it."""
        with TemporaryDirectory() as tmp:
            # `never_reached`'s BODY returns a value distinct from `reached`'s
            # (not just a distinct function name) on purpose: a `def` line
            # always executes at import time regardless of whether the
            # function is ever CALLED, so an anchor spanning the `def` line
            # would read as "covered" even for a function nothing calls. Both
            # mutation anchors below are scoped to a body line only, and each
            # body string is unique in the file so `_anchor_lines`'
            # first-occurrence search lands on the right function.
            files = {
                "pkg/mod.py": (
                    "def reached(x):\n"
                    "    if x:\n"
                    "        return True\n"
                    "    return False\n"
                    "\n"
                    "def never_reached(x):\n"
                    "    if x:\n"
                    "        return 'NEVER'\n"
                    "    return False\n"
                ),
                "pkg/__init__.py": "",
                "test_pkg.py": (
                    "from pkg.mod import reached\n"
                    "def test_it():\n"
                    "    assert reached(1) is True\n"
                ),
            }

            class _Sandbox:
                def __init__(self):
                    self.repo = None
                    self.error = None

                def build(self):
                    self.repo = Path(tmp) / "sandbox"
                    for rel, content in files.items():
                        p = self.repo / rel
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(content, encoding="utf-8")
                    return True

                def head(self):
                    return "f" * 40

                def destroy(self):
                    pass

            reached_mut = gd.Mutation(
                "reached_guard", "logic", "pkg/mod.py",
                "        return True", "        return False", "covered")
            never_mut = gd.Mutation(
                "never_reached_guard", "logic", "pkg/mod.py",
                "        return 'NEVER'", "        return 'MUTATED'", "uncovered")

            calls: list[str] = []

            def scripted_runner(repo, paths, timeout_s):
                calls.append("gate_run")
                # baseline, then one call per mutant actually applied
                return (len(calls) == 1), 0, "output"

            with mock.patch.object(gd, "MUTATIONS", (reached_mut, never_mut)):
                result = gd.run_corpus(
                    gate_runner=scripted_runner,
                    sandbox_factory=_Sandbox,
                    coverage_guided=True)

        self.assertEqual(result["state"], "measured")
        self.assertEqual(result["coverage_state"], "measured")
        # Only ONE mutant actually ran the gate after the baseline: the
        # uncovered one was skipped before ever reaching scripted_runner.
        self.assertEqual(calls.count("gate_run"), 2)  # baseline + reached_mut
        statuses = {r["id"]: r["status"] for r in result["results"]}
        self.assertEqual(statuses["never_reached_guard"], gd.STATUS_UNCOVERED)
        self.assertIn(statuses["reached_guard"], (gd.STATUS_CAUGHT, gd.STATUS_SURVIVED))
        excluded_ids = {r["id"] for r in result["excluded"]}
        self.assertIn("never_reached_guard", excluded_ids)


class RunCorpusCoverageWiringTests(unittest.TestCase):
    """Fast, fully faked: coverage_runner is injected so no real coverage.py
    or pytest run happens here -- only the wiring inside run_corpus."""

    def _files_for(self, mut_id: str) -> dict:
        mut = next(m for m in gd.MUTATIONS if m.id == mut_id)
        return {mut.file: f"before\n{mut.find}\nafter\n"}, mut

    def test_coverage_runner_returning_none_runs_every_mutant(self):
        files, mut = self._files_for("attempt_reap_unwired")
        result = gd.run_corpus(
            only=mut.id,
            gate_runner=scripted_gate_runner([True, False]),
            sandbox_factory=lambda: FakeSandbox(files),
            coverage_guided=True,
            coverage_runner=lambda repo, paths, timeout: None)
        self.assertEqual(result["coverage_state"], "unavailable")
        self.assertEqual(result["planted"], 1)
        self.assertEqual(result["results"][0]["status"], gd.STATUS_CAUGHT)

    def test_coverage_guided_false_never_calls_the_coverage_runner(self):
        files, mut = self._files_for("attempt_reap_unwired")
        probe_calls = []

        def probe(repo, paths, timeout):
            probe_calls.append(1)
            return {}

        result = gd.run_corpus(
            only=mut.id,
            gate_runner=scripted_gate_runner([True, False]),
            sandbox_factory=lambda: FakeSandbox(files),
            coverage_guided=False,
            coverage_runner=probe)
        self.assertEqual(result["coverage_state"], "not_requested")
        self.assertEqual(probe_calls, [])

    def test_prefer_diff_touched_reorders_without_dropping(self):
        result = gd.run_corpus(
            gate_runner=scripted_gate_runner([True] + [True] * len(gd.MUTATIONS)),
            sandbox_factory=lambda: FakeSandbox(
                {m.file: f"before\n{m.find}\nafter\n" for m in gd.MUTATIONS}),
            prefer_diff_touched=frozenset({"daedalus/offload.py"}))
        ids = [r["id"] for r in result["results"]]
        self.assertEqual(set(ids), {m.id for m in gd.MUTATIONS})
        self.assertEqual(ids[0], "offload_escalation_gate_disabled")


if __name__ == "__main__":
    unittest.main()
