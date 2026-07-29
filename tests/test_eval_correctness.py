"""Tests for daedalus.eval.correctness -- the FAIL_TO_PASS/PASS_TO_PASS evaluator.

EVERY GUARD IN THIS FILE HAS BEEN VERIFIED RED BY ACTUALLY DISABLING IT, not by
being written and assumed to bite. The disable-and-observe run is recorded in
``tools/`` -- see the module-level RED COUNTS comment below for what each guard
is and which test kills it.

Most tests drive the state machine through an injected runner (no subprocess,
no git) because the interesting behaviour is the JUDGEMENT, not pytest. Two
tests are deliberately end-to-end against a real throwaway git repository with
a real bug, a real fix and a real pytest run, because a judgement layered on a
parser that was never pointed at real output is a judgement about nothing.

RED COUNTS: 19 of the 20 disable points turned a test red. The one that did not
is ``_safe_join``'s absolute-path branch, which is DOMINATED by the containment
comparison beside it (measured, not reasoned) and is documented in the source as
a fast path rather than counted as a guard.

  guard -> the test that goes red when the guard is disabled:
  G1  _refuse_primary_checkout        PrimaryCheckoutGuardTests (x3)
  G2  _safe_join containment          OverlayEscapeTests.test_a_relative_escape_*
  G3  empty fail_to_pass is invalid   SchemaTests.test_empty_fail_to_pass_*
  G4  F2P passing on base -> invalid  BeforeStateTests.test_a_fail_to_pass_that_passes_*
  G5  P2P failing on base -> invalid  BeforeStateTests.test_a_pass_to_pass_that_fails_*
  G6  regressed outranks fixed        AfterStateTests.test_a_patch_that_fixes_and_breaks_*
  G7  no verdict -> could_not_run     BeforeStateTests/AfterStateTests no-verdict tests
  G8  gate refuses unverified task    GateTests.test_gate_refuses_a_task_*
  G9  gate refuses a moved selection  GateTests.test_gate_refuses_a_widened_* (x3)
  G10 _check_selection                SelectionTests.test_a_run_that_widens_*
  G11 harness refuses correctness     HarnessRefusalTests (x3)
  G12 _git_read verb allowlist        GitReadTests.test_a_mutating_verb_*
  G13 skipped/missing are not proof   BeforeStateTests.test_a_skipped_*, test_a_missing_*
  G14 not-found vs no-collectors      ParseTests.test_a_file_that_cannot_be_collected_*
  G15 xfail is not a pass             ParseTests.test_an_expected_failure_is_not_a_pass
  G16 frozen selection is authority   SelectionTests.test_mutating_the_task_*
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from daedalus.eval import correctness as C
from daedalus.eval import harness
from daedalus.eval.tasks import AGENT_ENV_ROOT, is_correctness_task


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
class ScriptedRunner:
    """An injected test runner that returns pre-scripted statuses.

    ``_run_lists`` calls a runner once per non-empty list, so an evaluation
    consumes up to four scripts: before-F2P, before-P2P, after-F2P, after-P2P.
    """

    def __init__(self, *scripts: dict):
        self.scripts = list(scripts)
        self.calls: list[list[str]] = []

    def __call__(self, worktree, node_ids, *, repo_root=None, timeout_s=None):
        self.calls.append(list(node_ids))
        script = self.scripts.pop(0) if self.scripts else {}
        statuses = {n: script.get(n, C.STATUS_NOT_RUN) for n in node_ids}
        # A script may also name a node that was NOT requested -- that is how
        # the "the run widened the selection" case is exercised.
        for extra, status in script.items():
            if extra not in statuses and extra.startswith("EXTRA:"):
                statuses[extra[len("EXTRA:"):]] = status
        return C.PytestRun(statuses=statuses, returncode=0, duration_s=0.0,
                           output="scripted", argv=("scripted",))


def a_task(**overrides) -> dict:
    task = {
        "id": "t1",
        "repo": "agent_env",
        "base_revision": "deadbee",
        "test_revision": "cafef00",
        "test_overlay": [],
        "fail_to_pass": ["tests/test_x.py::test_bug"],
        "pass_to_pass": ["tests/test_x.py::test_other"],
    }
    task.update(overrides)
    return task


F2P = "tests/test_x.py::test_bug"
P2P = "tests/test_x.py::test_other"


# --------------------------------------------------------------------------- #
# G3 -- the schema, and the anti-vacuity rule                                  #
# --------------------------------------------------------------------------- #
class SchemaTests(unittest.TestCase):
    def test_a_well_formed_task_has_no_problems(self):
        self.assertEqual(C.validate_task(a_task()), [])

    def test_empty_fail_to_pass_is_refused_not_treated_as_an_empty_success(self):
        """The exact shape of ``_recall([]) == 1.0``: a measurement that cannot
        fail. A task with no red-to-green test must never be evaluable."""
        problems = C.validate_task(a_task(fail_to_pass=[]))
        self.assertTrue(any("fail_to_pass" in p for p in problems), problems)

    def test_empty_fail_to_pass_can_never_reach_an_outcome_other_than_invalid(self):
        res = C.evaluate_change(a_task(fail_to_pass=[]), patch_bytes=b"x",
                                runner=ScriptedRunner())
        self.assertEqual(res.outcome, C.OUTCOME_TASK_INVALID)
        self.assertFalse(res.ok)

    def test_a_node_id_without_a_double_colon_is_refused(self):
        problems = C.validate_task(a_task(fail_to_pass=["tests/test_x.py"]))
        self.assertTrue(any("node id" in p for p in problems), problems)

    def test_the_same_node_cannot_be_in_both_lists(self):
        problems = C.validate_task(a_task(fail_to_pass=[F2P], pass_to_pass=[F2P]))
        self.assertTrue(any("both lists" in p for p in problems), problems)

    def test_five_outcomes_exist_and_are_distinct(self):
        self.assertEqual(len(set(C.OUTCOMES)), 5)
        self.assertEqual(set(C.OUTCOMES), {
            "fixed", "not_fixed", "regressed", "could_not_run", "task_invalid"})


# --------------------------------------------------------------------------- #
# G4, G5, G7, G13 -- the before state                                          #
# --------------------------------------------------------------------------- #
class BeforeStateTests(unittest.TestCase):
    def test_the_honest_case_verifies(self):
        before = C.judge_before_state("sha", {F2P: C.STATUS_FAILED},
                                      {P2P: C.STATUS_PASSED})
        self.assertTrue(before.verified)
        self.assertFalse(before.invalid)

    def test_a_fail_to_pass_that_passes_on_the_base_makes_the_task_invalid(self):
        """G4. The claim is refuted: this test cannot demonstrate a fix."""
        before = C.judge_before_state("sha", {F2P: C.STATUS_PASSED},
                                      {P2P: C.STATUS_PASSED})
        self.assertFalse(before.verified)
        self.assertTrue(before.invalid)
        self.assertTrue(any("already PASSES" in r for r in before.reasons),
                        before.reasons)

    def test_a_pass_to_pass_that_fails_on_the_base_makes_the_task_invalid(self):
        """G5, the mirror of G4 and just as load-bearing: a regression set that
        is already red cannot detect a regression."""
        before = C.judge_before_state("sha", {F2P: C.STATUS_FAILED},
                                      {P2P: C.STATUS_FAILED})
        self.assertFalse(before.verified)
        self.assertTrue(before.invalid)
        self.assertTrue(any("already red" in r for r in before.reasons),
                        before.reasons)

    def test_a_skipped_fail_to_pass_is_not_proof_that_it_fails(self):
        """G13. A skip is not evidence in either direction."""
        before = C.judge_before_state("sha", {F2P: C.STATUS_SKIPPED},
                                      {P2P: C.STATUS_PASSED})
        self.assertFalse(before.verified)
        self.assertTrue(before.invalid)

    def test_a_missing_fail_to_pass_names_a_test_that_is_not_there(self):
        """G13. The node id does not exist even with the overlay applied."""
        before = C.judge_before_state("sha", {F2P: C.STATUS_MISSING},
                                      {P2P: C.STATUS_PASSED})
        self.assertTrue(before.invalid)
        self.assertTrue(any("does not exist" in r for r in before.reasons),
                        before.reasons)

    def test_a_collection_error_IS_proof_that_it_does_not_pass(self):
        """The normal state of a test added by the fix: at the base revision its
        file imports something that is not there yet."""
        before = C.judge_before_state("sha", {F2P: C.STATUS_COLLECT_ERROR},
                                      {P2P: C.STATUS_PASSED})
        self.assertTrue(before.verified)

    def test_no_verdict_is_unrunnable_and_never_invalid_or_passing(self):
        """G7. 'We could not measure it' is a third thing, not a verdict."""
        before = C.judge_before_state("sha", {F2P: C.STATUS_NOT_RUN},
                                      {P2P: C.STATUS_PASSED})
        self.assertFalse(before.verified)
        self.assertTrue(before.unrunnable)
        self.assertFalse(before.invalid)

    def test_an_invalid_before_state_makes_the_whole_evaluation_task_invalid(self):
        runner = ScriptedRunner({F2P: C.STATUS_PASSED}, {P2P: C.STATUS_PASSED})
        res = C.evaluate_change(a_task(base_revision="HEAD"), patch_bytes=b"x",
                                runner=runner, repo_root=AGENT_ENV_ROOT)
        self.assertEqual(res.outcome, C.OUTCOME_TASK_INVALID)
        self.assertIn("already PASSES", res.reason)

    def test_an_unmeasurable_before_state_is_could_not_run_not_invalid(self):
        runner = ScriptedRunner({F2P: C.STATUS_NOT_RUN}, {P2P: C.STATUS_PASSED})
        res = C.evaluate_change(a_task(base_revision="HEAD"), patch_bytes=b"x",
                                runner=runner, repo_root=AGENT_ENV_ROOT)
        self.assertEqual(res.outcome, C.OUTCOME_COULD_NOT_RUN)


# --------------------------------------------------------------------------- #
# G6, G7 -- the after state and outcome precedence                             #
# --------------------------------------------------------------------------- #
class AfterStateTests(unittest.TestCase):
    def setUp(self):
        self.before = C.judge_before_state("sha", {F2P: C.STATUS_FAILED},
                                           {P2P: C.STATUS_PASSED})

    def test_a_patch_that_fixes_it_is_fixed(self):
        outcome, _r, fixed, unfixed, regressed = C.judge_after_state(
            self.before, {F2P: C.STATUS_PASSED}, {P2P: C.STATUS_PASSED})
        self.assertEqual(outcome, C.OUTCOME_FIXED)
        self.assertEqual(list(fixed), [F2P])
        self.assertEqual(list(unfixed), [])

    def test_a_patch_that_does_not_fix_it_is_not_fixed(self):
        outcome, _r, _f, unfixed, _reg = C.judge_after_state(
            self.before, {F2P: C.STATUS_FAILED}, {P2P: C.STATUS_PASSED})
        self.assertEqual(outcome, C.OUTCOME_NOT_FIXED)
        self.assertEqual(list(unfixed), [F2P])

    def test_a_patch_that_fixes_and_breaks_is_REGRESSED_not_fixed(self):
        """G6. The precedence that a single boolean would collapse: this patch
        turns every FAIL_TO_PASS green AND breaks the regression set."""
        outcome, reason, fixed, _u, regressed = C.judge_after_state(
            self.before, {F2P: C.STATUS_PASSED}, {P2P: C.STATUS_FAILED})
        self.assertEqual(outcome, C.OUTCOME_REGRESSED)
        self.assertEqual(list(regressed), [P2P])
        self.assertEqual(list(fixed), [F2P])   # it DID fix it, and that is said
        self.assertIn("broke", reason)

    def test_a_skipped_test_after_the_change_is_not_a_pass(self):
        outcome, _r, _f, unfixed, _reg = C.judge_after_state(
            self.before, {F2P: C.STATUS_SKIPPED}, {P2P: C.STATUS_PASSED})
        self.assertEqual(outcome, C.OUTCOME_NOT_FIXED)
        self.assertEqual(list(unfixed), [F2P])

    def test_no_verdict_after_the_change_is_could_not_run(self):
        """G7. Never a pass, never a fail -- an unknown stays unknown."""
        outcome, _r, _f, _u, _reg = C.judge_after_state(
            self.before, {F2P: C.STATUS_NOT_RUN}, {P2P: C.STATUS_PASSED})
        self.assertEqual(outcome, C.OUTCOME_COULD_NOT_RUN)

    def test_a_test_already_red_before_is_not_counted_as_a_regression(self):
        before = C.judge_before_state("sha", {F2P: C.STATUS_FAILED},
                                      {P2P: C.STATUS_FAILED})
        outcome, _r, _f, _u, regressed = C.judge_after_state(
            before, {F2P: C.STATUS_PASSED}, {P2P: C.STATUS_FAILED})
        self.assertEqual(list(regressed), [])
        self.assertEqual(outcome, C.OUTCOME_FIXED)


# --------------------------------------------------------------------------- #
# G10, G16 -- the frozen selection                                             #
# --------------------------------------------------------------------------- #
class SelectionTests(unittest.TestCase):
    def test_the_digest_covers_every_field_that_can_change_a_result(self):
        base = C.freeze_selection(a_task(), "sha")
        for changed in (a_task(fail_to_pass=[F2P, "tests/test_x.py::test_two"]),
                        a_task(pass_to_pass=[]),
                        a_task(test_overlay=["tests/test_x.py"],
                               test_revision="r")):
            self.assertNotEqual(C.freeze_selection(changed, "sha").digest,
                                base.digest, changed)
        self.assertNotEqual(C.freeze_selection(a_task(), "other").digest,
                            base.digest)

    def test_the_digest_is_stable_across_declaration_order(self):
        one = C.freeze_selection(a_task(fail_to_pass=["a::b", "c::d"]), "sha")
        two = C.freeze_selection(a_task(fail_to_pass=["c::d", "a::b"]), "sha")
        self.assertEqual(one.digest, two.digest)

    def test_a_run_that_widens_the_selection_is_refused(self):
        """G10. A node nobody declared cannot contribute to a verdict."""
        selection = C.freeze_selection(a_task(), "sha")
        moved = C._check_selection(selection, {F2P: C.STATUS_PASSED,
                                               "tests/test_new.py::test_added":
                                               C.STATUS_PASSED},
                                   {P2P: C.STATUS_PASSED})
        self.assertIsNotNone(moved)
        self.assertIn("may not widen", moved)

    def test_a_run_that_narrows_the_selection_is_refused(self):
        selection = C.freeze_selection(a_task(), "sha")
        moved = C._check_selection(selection, {F2P: C.STATUS_PASSED}, {})
        self.assertIsNotNone(moved)
        self.assertIn("may not narrow", moved)

    def test_a_widened_run_makes_the_evaluation_could_not_run(self):
        runner = ScriptedRunner({F2P: C.STATUS_FAILED,
                                 "EXTRA:tests/test_new.py::test_added": C.STATUS_PASSED},
                                {P2P: C.STATUS_PASSED})
        res = C.evaluate_change(a_task(base_revision="HEAD"), patch_bytes=b"x",
                                runner=runner, repo_root=AGENT_ENV_ROOT)
        self.assertEqual(res.outcome, C.OUTCOME_COULD_NOT_RUN)
        self.assertIn("may not widen", res.reason)

    def test_mutating_the_task_after_the_freeze_changes_nothing(self):
        """G16. The task dict is not the authority once a selection is frozen --
        a runner (or anything else holding the same dict) cannot widen the set
        by editing it mid-evaluation."""
        task = a_task(base_revision="HEAD")
        selection = C.freeze_selection(task, "sha")
        task["fail_to_pass"].append("tests/test_new.py::test_added")
        task["pass_to_pass"] = []
        runner = ScriptedRunner({F2P: C.STATUS_FAILED}, {P2P: C.STATUS_PASSED})
        f2p, p2p = C._run_lists(runner, Path("."), selection, AGENT_ENV_ROOT, [])
        self.assertEqual(runner.calls[0], [F2P])
        self.assertEqual(runner.calls[1], [P2P])
        self.assertEqual(set(f2p), {F2P})
        self.assertEqual(set(p2p), {P2P})

    def test_the_receipt_records_the_declaration_and_its_digest(self):
        selection = C.freeze_selection(a_task(), "sha")
        receipt = C.judge_before_state("sha", {F2P: C.STATUS_FAILED},
                                       {P2P: C.STATUS_PASSED},
                                       selection=selection).to_dict()
        self.assertEqual(receipt["selection_digest"], selection.digest)
        self.assertEqual(receipt["selection"]["fail_to_pass"], [F2P])
        self.assertEqual(receipt["selection"]["base_revision"], "sha")

    def test_freezing_never_reads_the_filesystem_for_node_ids(self):
        """There is no glob: a selection is exactly what was declared, so a test
        file a candidate adds can never enter the set."""
        selection = C.freeze_selection(
            a_task(fail_to_pass=["tests/test_does_not_exist.py::test_nope"]), "sha")
        self.assertEqual(list(selection.fail_to_pass),
                         ["tests/test_does_not_exist.py::test_nope"])


# --------------------------------------------------------------------------- #
# G14, G15 -- parsing real pytest output                                       #
# --------------------------------------------------------------------------- #
class ParseTests(unittest.TestCase):
    def test_verbose_progress_lines_are_attributed_per_node(self):
        text = ("tests/test_x.py::test_bug FAILED   [ 50%]\n"
                "tests/test_x.py::test_other PASSED  [100%]\n")
        self.assertEqual(C.parse_pytest_output(text, [F2P, P2P]),
                         {F2P: C.STATUS_FAILED, P2P: C.STATUS_PASSED})

    def test_a_skip_keeps_its_node_id_which_is_why_v_is_used_over_rA(self):
        text = "tests/test_x.py::test_bug SKIPPED (nope)  [100%]\n"
        self.assertEqual(C.parse_pytest_output(text, [F2P])[F2P], C.STATUS_SKIPPED)

    def test_a_node_that_is_not_mentioned_at_all_is_not_run(self):
        self.assertEqual(C.parse_pytest_output("", [F2P])[F2P], C.STATUS_NOT_RUN)

    def test_a_node_id_that_does_not_exist_is_missing(self):
        text = r"ERROR: not found: C:\repo\tests\test_x.py::test_bug"
        self.assertEqual(C.parse_pytest_output(text, [F2P])[F2P], C.STATUS_MISSING)

    def test_a_file_that_cannot_be_collected_is_a_collect_error_not_missing(self):
        """G14. Two different facts, and conflating them cost 13 of 14 nodes of a
        real corpus candidate: 'the node does not exist' refutes the TASK, while
        'the file does not import on the base revision' is the NORMAL before-state
        of a test the fix adds."""
        text = (r"ERROR: found no collectors for C:\repo\tests\test_x.py::test_bug"
                "\nERROR tests/test_x.py\n")
        self.assertEqual(C.parse_pytest_output(text, [F2P])[F2P],
                         C.STATUS_COLLECT_ERROR)

    def test_an_expected_failure_is_not_a_pass(self):
        """G15. An xfail-marked test is red before and red after; it can never
        witness a fix. Measured on this repo: a real fix commit's own test was
        xfail-marked, and treating XFAIL as a pass would have admitted it."""
        text = "tests/test_x.py::test_bug XFAIL  [100%]\n"
        self.assertEqual(C.parse_pytest_output(text, [F2P])[F2P], C.STATUS_FAILED)

    def test_a_parametrized_node_takes_the_worst_of_its_cases(self):
        text = ("tests/test_x.py::test_bug[1] PASSED  [ 50%]\n"
                "tests/test_x.py::test_bug[2] FAILED  [100%]\n")
        self.assertEqual(C.parse_pytest_output(text, [F2P])[F2P], C.STATUS_FAILED)

    def test_absolute_paths_in_pytest_output_match_relative_node_ids(self):
        text = "C:/repo/tests/test_x.py::test_bug PASSED [100%]\n"
        self.assertEqual(C.parse_pytest_output(text, [F2P])[F2P], C.STATUS_PASSED)

    def test_the_argv_uses_this_interpreter_and_disables_the_cache(self):
        argv = C.pytest_node_argv([F2P])
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("-p", argv)
        self.assertIn("no:cacheprovider", argv)
        self.assertIn(F2P, argv)
        self.assertIn("-v", argv)   # per-node attribution; -q cannot give it

    def test_the_argv_shape_still_matches_the_repos_own_pytest_gate(self):
        """Drift alarm: if spine's gate argv changes shape, this notices."""
        from daedalus.spine.attempt import pytest_gate_argv

        theirs = pytest_gate_argv(["x"])
        mine = C.pytest_node_argv(["x"])
        self.assertEqual(theirs[:3], mine[:3])
        self.assertEqual(theirs[-2:], ("-p", "no:cacheprovider"))
        self.assertEqual(mine[-2:], ("-p", "no:cacheprovider"))


# --------------------------------------------------------------------------- #
# G1, G2, G12 -- isolation from the primary checkout                           #
# --------------------------------------------------------------------------- #
class PrimaryCheckoutGuardTests(unittest.TestCase):
    def test_the_primary_checkout_is_refused_as_a_pytest_directory(self):
        """G1. This repo has already lost a working tree to a cleanup path that
        could not possibly reach it."""
        with self.assertRaises(C.PrimaryCheckoutTouch):
            C.run_node_ids(AGENT_ENV_ROOT, [F2P], repo_root=AGENT_ENV_ROOT)

    def test_a_directory_inside_the_primary_checkout_is_refused(self):
        with self.assertRaises(C.PrimaryCheckoutTouch):
            C._refuse_primary_checkout(os.path.join(AGENT_ENV_ROOT, "daedalus"),
                                       AGENT_ENV_ROOT)

    def test_the_primary_checkout_is_refused_as_a_patch_target(self):
        with self.assertRaises(C.PrimaryCheckoutTouch):
            C.apply_patch(AGENT_ENV_ROOT, AGENT_ENV_ROOT, b"diff --git a/x b/x\n")

    def test_a_directory_outside_the_checkout_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(C._refuse_primary_checkout(tmp, AGENT_ENV_ROOT))


class OverlayEscapeTests(unittest.TestCase):
    def test_a_relative_escape_is_refused(self):
        """G2. ``test_overlay`` is data; ../.. is an ordinary-looking string."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(C.OverlayEscape):
                C._safe_join(tmp, "../../daedalus/spine/attempt.py")

    def test_an_absolute_path_is_refused(self):
        """NOT a second guard: measured by disabling the ``isabs`` branch, this
        test still passes, because the containment comparison catches an
        absolute path on its own. Kept as a behaviour test of the refusal, and
        the branch is documented as a fast path rather than claimed as tested --
        an untested branch presented as a guard is how the previous round of
        ``kairos/worktree.py`` shipped green over a live bug."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(C.OverlayEscape):
                C._safe_join(tmp, os.path.join(AGENT_ENV_ROOT, "daedalus", "cli.py"))

    def test_an_ordinary_relative_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = C._safe_join(tmp, "tests/test_x.py")
            self.assertTrue(str(got).startswith(str(Path(tmp).resolve())[:3]))
            self.assertIn("test_x.py", str(got))


class GitReadTests(unittest.TestCase):
    def test_a_mutating_verb_aimed_at_the_primary_checkout_is_refused(self):
        """G12. Reuses spine.attempt's own allowlist rather than a second copy."""
        for verb in ("add", "commit", "checkout", "reset", "apply", "clean"):
            with self.assertRaises(C.PrimaryCheckoutTouch):
                C._git_read(AGENT_ENV_ROOT, verb, "-A")

    def test_a_read_verb_is_allowed(self):
        proc = C._git_read(AGENT_ENV_ROOT, "rev-parse", "HEAD")
        self.assertEqual(proc.returncode, 0)


# --------------------------------------------------------------------------- #
# G8, G9 -- the gate wiring                                                    #
# --------------------------------------------------------------------------- #
class _Ctx:
    def __init__(self, worktree, base_revision):
        self.worktree = worktree
        self.base_revision = base_revision
        self.branch = "b"
        self.is_cancelled = lambda: False


def _verified_task(**overrides) -> dict:
    task = a_task(base_revision="a" * 40, **overrides)
    selection = C.freeze_selection(task, task["base_revision"])
    task["before_state"] = C.judge_before_state(
        task["base_revision"], {n: C.STATUS_FAILED for n in task["fail_to_pass"]},
        {n: C.STATUS_PASSED for n in task["pass_to_pass"]},
        selection=selection).to_dict()
    return task


class GateTests(unittest.TestCase):
    def test_the_gate_passes_a_patch_that_fixes_it(self):
        task = _verified_task()
        gate = C.correctness_gate(task, AGENT_ENV_ROOT,
                                  runner=ScriptedRunner({F2P: C.STATUS_PASSED},
                                                        {P2P: C.STATUS_PASSED}))
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertTrue(verdict.passed)
        self.assertIn("fixed", verdict.output)

    def test_the_gate_fails_a_patch_that_does_not_fix_it(self):
        task = _verified_task()
        gate = C.correctness_gate(task, AGENT_ENV_ROOT,
                                  runner=ScriptedRunner({F2P: C.STATUS_FAILED},
                                                        {P2P: C.STATUS_PASSED}))
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertFalse(verdict.passed)
        self.assertIn("not_fixed", verdict.output)

    def test_the_gate_fails_a_patch_that_breaks_the_regression_set(self):
        task = _verified_task()
        gate = C.correctness_gate(task, AGENT_ENV_ROOT,
                                  runner=ScriptedRunner({F2P: C.STATUS_PASSED},
                                                        {P2P: C.STATUS_FAILED}))
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertFalse(verdict.passed)
        self.assertIn("regressed", verdict.output)

    def test_gate_refuses_a_task_with_no_verified_before_state(self):
        """G8. Fail closed: a FAIL_TO_PASS list that was never shown to fail
        certifies nothing, and the attempt's worktree is already dirty so the
        gate cannot measure it here."""
        task = a_task(base_revision="a" * 40)
        gate = C.correctness_gate(task, AGENT_ENV_ROOT,
                                  runner=ScriptedRunner({F2P: C.STATUS_PASSED},
                                                        {P2P: C.STATUS_PASSED}))
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertFalse(verdict.passed)
        self.assertIn("no VERIFIED before-state", verdict.output)

    def test_gate_refuses_a_widened_selection(self):
        """G9. The set was frozen before the candidate ran. A test the candidate
        itself added cannot be admitted afterwards."""
        task = _verified_task()
        task["fail_to_pass"] = list(task["fail_to_pass"]) + [
            "tests/test_candidate_added.py::test_it_works"]
        gate = C.correctness_gate(task, AGENT_ENV_ROOT, runner=ScriptedRunner())
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertFalse(verdict.passed)
        self.assertIn("not the one that was verified", verdict.output)

    def test_gate_refuses_a_narrowed_selection(self):
        task = _verified_task()
        task["pass_to_pass"] = []
        gate = C.correctness_gate(task, AGENT_ENV_ROOT, runner=ScriptedRunner())
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertFalse(verdict.passed)
        self.assertIn("not the one that was verified", verdict.output)

    def test_gate_refuses_a_receipt_with_no_selection_digest(self):
        task = _verified_task()
        task["before_state"].pop("selection_digest")
        gate = C.correctness_gate(task, AGENT_ENV_ROOT, runner=ScriptedRunner())
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertFalse(verdict.passed)
        self.assertIn("no selection digest", verdict.output)

    def test_gate_refuses_a_before_state_measured_at_another_revision(self):
        task = _verified_task()
        gate = C.correctness_gate(task, AGENT_ENV_ROOT, runner=ScriptedRunner())
        verdict = gate(_Ctx(Path("."), "b" * 40))
        self.assertFalse(verdict.passed)
        self.assertIn("a tree that is not this one", verdict.output)

    def test_the_gate_matches_the_attempts_gate_contract(self):
        """It must be droppable into TaskAttempt(gate=...) with no spine edit."""
        from daedalus.spine.attempt import GateResult

        task = _verified_task()
        gate = C.correctness_gate(task, AGENT_ENV_ROOT,
                                  runner=ScriptedRunner({F2P: C.STATUS_PASSED},
                                                        {P2P: C.STATUS_PASSED}))
        verdict = gate(_Ctx(Path("."), task["base_revision"]))
        self.assertIsInstance(verdict, GateResult)
        self.assertIsInstance(verdict.summary(), dict)


# --------------------------------------------------------------------------- #
# G11 -- the harness must never score a correctness task with slice recall     #
# --------------------------------------------------------------------------- #
class HarnessRefusalTests(unittest.TestCase):
    def test_the_predicate_sees_an_empty_test_list_as_a_correctness_task(self):
        self.assertTrue(is_correctness_task({"fail_to_pass": []}))
        self.assertTrue(is_correctness_task({"pass_to_pass": ["a::b"]}))
        self.assertFalse(is_correctness_task({"must_include": ["x"]}))

    def test_tier1_refuses_a_correctness_task_instead_of_scoring_it_1_0(self):
        """G11. With no ``must_include`` the slice recall would be a vacuous
        1.0 -- a task that cannot fail, inflating the go/no-go number."""
        row = harness.eval_task_tier1(a_task(target="daedalus/eval/harness.py"))
        self.assertIn("error", row)
        self.assertNotIn("recall", row)
        self.assertTrue(row.get("correctness_task"))

    def test_arms_refuses_a_correctness_task_in_every_arm(self):
        row = harness.eval_task_arms(a_task(target="daedalus/eval/harness.py"))
        self.assertIn("error", row)
        for key in ("recall_A", "recall_B", "recall_C"):
            self.assertNotIn(key, row)

    def test_run_tier1_refuses_one_even_when_it_cannot_resolve_a_repo(self):
        result = harness.run_tier1([{"id": "c1", "fail_to_pass": ["a::b"]}])
        self.assertEqual(result["n_errored_tasks"], 1)
        self.assertEqual(result["by_provenance"], {})

    def test_a_refused_correctness_task_fails_the_gate_loudly(self):
        gate = harness.run_gate([a_task(id="c2", tier="primary")])
        self.assertFalse(gate["passed"])
        self.assertEqual([r["id"] for r in gate["errored_primary"]], ["c2"])


# --------------------------------------------------------------------------- #
# the corpus that ships with the repo                                          #
# --------------------------------------------------------------------------- #
class CorpusTests(unittest.TestCase):
    def test_every_corpus_task_satisfies_the_schema(self):
        for task in C.load_correctness_tasks():
            self.assertEqual(C.validate_task(task), [], task["id"])

    def test_every_corpus_task_carries_a_verified_before_state_receipt(self):
        tasks = C.load_correctness_tasks()
        self.assertGreater(len(tasks), 0, "the seeded corpus is missing")
        for task in tasks:
            receipt = task["before_state"]
            self.assertTrue(receipt["verified"], task["id"])
            self.assertEqual(receipt["base_revision"], task["base_revision"])
            for node, status in receipt["fail_to_pass"].items():
                self.assertIn(status, C.PROVEN_NOT_PASSING, f"{task['id']} {node}")
            for node, status in receipt["pass_to_pass"].items():
                self.assertEqual(status, C.STATUS_PASSED, f"{task['id']} {node}")

    def test_every_corpus_receipt_matches_the_task_it_is_stored_on(self):
        """The stored digest is checkable, so a hand-edited corpus is caught."""
        for task in C.load_correctness_tasks():
            selection = C.freeze_selection(task, task["base_revision"])
            self.assertEqual(task["before_state"]["selection_digest"],
                             selection.digest, task["id"])

    def test_the_corpus_records_what_it_dropped_and_why(self):
        dropped = {t["id"]: t.get("dropped_candidates", {})
                   for t in C.load_correctness_tasks()}
        self.assertTrue(any(v for v in dropped.values()),
                        "a corpus that dropped nothing is not reporting")

    def test_the_corpus_is_not_reachable_from_the_slice_recall_corpus(self):
        ids = {t["id"] for t in harness.all_tasks()}
        for task in C.load_correctness_tasks():
            self.assertNotIn(task["id"], ids)


# --------------------------------------------------------------------------- #
# end to end, against a real throwaway repository                              #
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True)


BUGGY = '''\
def unique_name(existing, base):
    """Return a name not already in `existing`."""
    return base
'''

FIXED = '''\
def unique_name(existing, base):
    """Return a name not already in `existing`."""
    if base not in existing:
        return base
    n = 1
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"
'''

TEST_BEFORE = '''\
from lib import unique_name


def test_a_fresh_name_is_returned():
    assert unique_name(set(), "a") == "a"
'''

TEST_AFTER = TEST_BEFORE + '''

def test_a_second_name_does_not_collide():
    assert unique_name({"a"}, "a") != "a"


def test_a_third_name_does_not_collide():
    seen = {"a", "a-1"}
    assert unique_name(seen, "a") not in seen
'''


class EndToEndTests(unittest.TestCase):
    """Real git, real worktree, real pytest. Slow on purpose: the judgement
    layer above is only worth what the parser under it is, and the parser is
    only worth what real pytest output makes it."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="daedalus-corr-e2e-")
        root = Path(cls._tmp.name)
        cls.repo = root / "repo"
        cls.repo.mkdir()
        cls._worktree_root = root / "worktrees"
        _git(cls.repo, "init", "-q", "-b", "main")
        _git(cls.repo, "config", "user.email", "t@example.com")
        _git(cls.repo, "config", "user.name", "t")
        (cls.repo / "lib.py").write_text(BUGGY, encoding="utf-8")
        (cls.repo / "tests").mkdir()
        (cls.repo / "tests" / "test_lib.py").write_text(TEST_BEFORE, encoding="utf-8")
        (cls.repo / "conftest.py").write_text("import sys, os\n"
                                              "sys.path.insert(0, os.path.dirname(__file__))\n",
                                              encoding="utf-8")
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-qm", "base: the bug")
        (cls.repo / "lib.py").write_text(FIXED, encoding="utf-8")
        (cls.repo / "tests" / "test_lib.py").write_text(TEST_AFTER, encoding="utf-8")
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-qm", "fix: unique names")
        cls.fix = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cls.repo),
                                 capture_output=True, text=True,
                                 check=True).stdout.strip()
        cls._prev_root = os.environ.get("DAEDALUS_WORKTREE_ROOT")
        os.environ["DAEDALUS_WORKTREE_ROOT"] = str(cls._worktree_root)

    @classmethod
    def tearDownClass(cls):
        if cls._prev_root is None:
            os.environ.pop("DAEDALUS_WORKTREE_ROOT", None)
        else:
            os.environ["DAEDALUS_WORKTREE_ROOT"] = cls._prev_root
        cls._tmp.cleanup()

    def test_seeding_measures_the_lists_instead_of_trusting_the_diff(self):
        task, diagnostics = C.seed_task_from_commit(self.repo, self.fix)
        self.assertIsNotNone(task, diagnostics)
        self.assertEqual(sorted(task["fail_to_pass"]), [
            "tests/test_lib.py::test_a_second_name_does_not_collide",
            "tests/test_lib.py::test_a_third_name_does_not_collide"])
        # The pre-existing test was green before and after: the regression set,
        # not a fix witness, and nothing had to be told that.
        self.assertEqual(task["pass_to_pass"],
                         ["tests/test_lib.py::test_a_fresh_name_is_returned"])
        self.assertTrue(task["before_state"]["verified"])
        self.assertTrue(task["before_state"]["selection_digest"])

        # ...and the task that came out of it reproduces `fixed` under its own
        # reference fix, measured from scratch in a NEW worktree.
        res = C.evaluate_change(task, use_reference=True, repo_root=str(self.repo))
        self.assertEqual(res.outcome, C.OUTCOME_FIXED, res.reason)
        self.assertEqual(len(res.fixed_nodes), 2)
        self.assertEqual(res.selection.digest,
                         task["before_state"]["selection_digest"])

    def test_a_wrong_but_plausible_patch_is_rejected(self):
        """The whole point. This patch fixes the SECOND collision and not the
        third -- exactly the defect the fix commit's third test exists to catch.
        ``pytest_gate`` (exit 0 over gate_paths) accepts it; this does not."""
        task, _diag = C.seed_task_from_commit(self.repo, self.fix)
        wrong = ('def unique_name(existing, base):\n'
                 '    """Return a name not already in `existing`."""\n'
                 '    if base not in existing:\n'
                 '        return base\n'
                 '    return f"{base}-1"\n')
        patch = _unified_diff("lib.py", BUGGY, wrong)
        res = C.evaluate_change(task, patch_bytes=patch, repo_root=str(self.repo))
        self.assertEqual(res.outcome, C.OUTCOME_NOT_FIXED, res.reason)
        self.assertEqual(list(res.unfixed_nodes),
                         ["tests/test_lib.py::test_a_third_name_does_not_collide"])
        self.assertEqual(list(res.fixed_nodes),
                         ["tests/test_lib.py::test_a_second_name_does_not_collide"])

    def test_a_no_op_patch_is_not_fixed_and_the_primary_checkout_is_untouched(self):
        task, _diag = C.seed_task_from_commit(self.repo, self.fix)
        patch = _unified_diff("lib.py", BUGGY, "# a comment\n" + BUGGY)
        before_status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(self.repo),
            capture_output=True, text=True, check=True).stdout
        res = C.evaluate_change(task, patch_bytes=patch, repo_root=str(self.repo))
        self.assertEqual(res.outcome, C.OUTCOME_NOT_FIXED, res.reason)
        after_status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(self.repo),
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(before_status, after_status)

    def test_a_patch_that_breaks_the_regression_set_is_regressed(self):
        task, _diag = C.seed_task_from_commit(self.repo, self.fix)
        sabotage = FIXED.replace('    if base not in existing:\n'
                                 '        return base\n', "")
        patch = _unified_diff("lib.py", BUGGY, sabotage)
        res = C.evaluate_change(task, patch_bytes=patch, repo_root=str(self.repo))
        self.assertEqual(res.outcome, C.OUTCOME_REGRESSED, res.reason)
        self.assertEqual(list(res.regressed_nodes),
                         ["tests/test_lib.py::test_a_fresh_name_is_returned"])

    def test_a_patch_that_does_not_apply_is_could_not_run_not_not_fixed(self):
        task, _diag = C.seed_task_from_commit(self.repo, self.fix)
        res = C.evaluate_change(task, patch_bytes=b"not a patch at all\n",
                                repo_root=str(self.repo))
        self.assertEqual(res.outcome, C.OUTCOME_COULD_NOT_RUN, res.reason)

    def test_an_invalid_task_is_reported_invalid_and_never_as_a_pass(self):
        """A FAIL_TO_PASS claim naming a test that is green on the base."""
        task, _diag = C.seed_task_from_commit(self.repo, self.fix)
        broken = dict(task)
        broken["fail_to_pass"] = ["tests/test_lib.py::test_a_fresh_name_is_returned"]
        broken["pass_to_pass"] = []
        broken.pop("before_state", None)
        res = C.evaluate_change(broken, use_reference=True, repo_root=str(self.repo))
        self.assertEqual(res.outcome, C.OUTCOME_TASK_INVALID, res.reason)
        self.assertIn("already PASSES", res.reason)
        self.assertFalse(res.ok)


def _unified_diff(rel: str, before: str, after: str) -> bytes:
    import difflib

    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}")).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
