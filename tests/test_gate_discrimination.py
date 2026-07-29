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


if __name__ == "__main__":
    unittest.main()
