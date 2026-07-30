"""The fan-out driver must be boring under failure and free on resume.

Every test here pins a property that a measured 2026-07-30 failure would have
violated. No test in this file makes a network call: ``_one_call`` is replaced,
which is also the point -- a driver whose failure behaviour can only be tested by
paying for it would never be tested.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from daedalus.lanes import fanout as F


def _answer(task, vote, repo_root, model, timeout_s, brief):
    return {"vote": vote, "report": {"summary": f"ok {task.task_id}"},
            "brief_len": len(brief), "notes": []}


class TaskIdentity(unittest.TestCase):
    def test_a_task_id_with_separators_cannot_escape_the_output_directory(self):
        for hostile in ("../../etc/passwd", "a/b/c.py@deadbeef",
                        "C:\\Windows\\system32", "x\0y"):
            with self.subTest(task_id=hostile):
                key = F.FanoutTask(task_id=hostile, objective="x").key
                self.assertNotIn("/", key)
                self.assertNotIn("\\", key)
                self.assertNotIn("..", key)
                self.assertNotIn("\0", key)

    def test_the_key_is_stable_and_distinguishes_similar_ids(self):
        a = F.FanoutTask(task_id="repo/x.py@aaa", objective="q")
        b = F.FanoutTask(task_id="repo/x.py@bbb", objective="q")
        # Stable across construction -- it is the resume identity.
        self.assertEqual(a.key, F.FanoutTask(task_id="repo/x.py@aaa",
                                            objective="different").key)
        # And two ids that sanitise to the same string must not collide, which is
        # why a digest is appended rather than the sanitised name being trusted.
        self.assertNotEqual(a.key, b.key)

    def test_ids_differing_only_in_a_sanitised_character_still_differ(self):
        self.assertNotEqual(F.FanoutTask(task_id="a/b", objective="q").key,
                            F.FanoutTask(task_id="a\\b", objective="q").key)


class ResumeIsFree(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.calls: list[int] = []

        def counting(task, vote, repo_root, model, timeout_s, brief):
            self.calls.append(vote)
            return _answer(task, vote, repo_root, model, timeout_s, brief)

        self._orig = F._one_call
        F._one_call = counting

    def tearDown(self):
        F._one_call = self._orig

    def test_a_complete_prior_result_is_not_paid_for_again(self):
        task = F.FanoutTask(task_id="t1", objective="q", votes=3)
        (self.dir / f"{task.key}.json").write_text(json.dumps({
            "task_id": "t1", "votes_requested": 3,
            "answers": [{"vote": 1, "report": "cached"}]}), encoding="utf-8")
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["paid_calls"], 0)
        self.assertEqual(out["resumed"], 1)
        self.assertEqual(out["ok"], 1)
        self.assertEqual(self.calls, [])

    def test_an_unparseable_prior_result_is_re_run_not_trusted(self):
        # A torn file reads as an answer, which is worse than a missing one --
        # the same reasoning as refusing a truncated model rewrite.
        task = F.FanoutTask(task_id="t2", objective="q", votes=2)
        (self.dir / f"{task.key}.json").write_text('{"answers": [{"vo',
                                                   encoding="utf-8")
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["paid_calls"], 2)
        self.assertEqual(out["resumed"], 0)

    def test_a_prior_result_with_zero_answers_is_re_run(self):
        # It recorded only errors last time; that is a task to retry, not a
        # result to keep.
        task = F.FanoutTask(task_id="t3", objective="q", votes=1)
        (self.dir / f"{task.key}.json").write_text(json.dumps({
            "task_id": "t3", "votes_requested": 1, "answers": [],
            "errors": ["timeout"]}), encoding="utf-8")
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["paid_calls"], 1)

    def test_resume_false_pays_again(self):
        task = F.FanoutTask(task_id="t4", objective="q", votes=1)
        (self.dir / f"{task.key}.json").write_text(json.dumps({
            "task_id": "t4", "votes_requested": 1,
            "answers": [{"vote": 1}]}), encoding="utf-8")
        out = F.fan_out([task], self.dir, concurrency=1, resume=False)
        self.assertEqual(out["paid_calls"], 1)


class OneFailureDoesNotKillTheQueue(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig = F._one_call

        def flaky(task, vote, repo_root, model, timeout_s, brief):
            if task.task_id == "boom":
                raise RuntimeError("transport exploded")
            return _answer(task, vote, repo_root, model, timeout_s, brief)

        F._one_call = flaky

    def tearDown(self):
        F._one_call = self._orig

    def test_the_run_completes_and_names_the_failure(self):
        tasks = [F.FanoutTask(task_id=f"t{i}", objective="q") for i in range(5)]
        tasks.append(F.FanoutTask(task_id="boom", objective="q"))
        out = F.fan_out(tasks, self.dir, concurrency=3)
        self.assertEqual(out["state"], "ran")
        self.assertEqual(out["ok"], 5)
        self.assertEqual(out["failed"], 1)
        # The failure is on disk, named, and re-runnable -- not swallowed.
        dead = next(r for r in out["results"] if r["task_id"] == "boom")
        self.assertEqual(dead["answers"], [])
        self.assertTrue(any("transport exploded" in e for e in dead["errors"]))
        self.assertTrue((self.dir / f"{dead['key']}.json").is_file())

    def test_every_task_lands_a_file_even_when_it_failed(self):
        tasks = [F.FanoutTask(task_id="boom", objective="q")]
        F.fan_out(tasks, self.dir, concurrency=1)
        self.assertEqual(len(list(self.dir.glob("*.json"))), 1)


class Corroboration(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig = F._one_call
        F._one_call = _answer

    def tearDown(self):
        F._one_call = self._orig

    def test_votes_produce_that_many_independent_answers(self):
        # N agents on the SAME question is what makes agreement a signal. The
        # 2026-07-30 fan-out gave every agent a different target and its largest
        # agreement cluster was two, out of 1,226 claims.
        task = F.FanoutTask(task_id="v", objective="q", votes=3)
        out = F.fan_out([task], self.dir, concurrency=2)
        self.assertEqual(out["paid_calls"], 3)
        got = out["results"][0]
        self.assertEqual(got["votes_collected"], 3)
        self.assertEqual(sorted(a["vote"] for a in got["answers"]), [1, 2, 3])

    def test_meta_survives_untouched_so_results_can_be_joined(self):
        task = F.FanoutTask(task_id="m", objective="q",
                            meta={"sha": "abc123", "lens": "refactor"})
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["results"][0]["meta"],
                         {"sha": "abc123", "lens": "refactor"})

    def test_paid_calls_is_reported_separately_from_task_count(self):
        tasks = [F.FanoutTask(task_id=f"t{i}", objective="q", votes=3)
                 for i in range(4)]
        out = F.fan_out(tasks, self.dir, concurrency=4)
        self.assertEqual(out["tasks"], 4)
        self.assertEqual(out["paid_calls"], 12)


class TheGraphBriefIsInjected(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig = F._one_call
        self.briefs: list[str] = []

        def capture(task, vote, repo_root, model, timeout_s, brief):
            self.briefs.append(brief)
            return _answer(task, vote, repo_root, model, timeout_s, brief)

        F._one_call = capture

    def tearDown(self):
        F._one_call = self._orig

    def test_a_task_with_paths_gets_a_brief(self):
        task = F.FanoutTask(task_id="b", objective="q",
                            paths=("daedalus/shift.py",))
        F.fan_out([task], self.dir, repo_root=".", concurrency=1)
        self.assertTrue(self.briefs and self.briefs[0],
                        "a path-bearing task must carry structural context; "
                        "three agent-invented module names on 2026-07-30 are "
                        "what its absence costs")
        self.assertIn("SYMBOLS THAT EXIST", self.briefs[0])

    def test_an_advisory_task_with_no_paths_gets_no_brief(self):
        task = F.FanoutTask(task_id="n", objective="q")
        F.fan_out([task], self.dir, repo_root=".", concurrency=1)
        self.assertEqual(self.briefs, [""])


class TheBudgetGuardIsNotOptional(unittest.TestCase):
    def test_a_fan_out_whose_spend_cannot_be_capped_refuses_to_run(self):
        # FAIL CLOSED. The alternative -- running unpriced and mentioning it in a
        # summary read after the invoice arrives -- is the measured 2026-07-30
        # failure: ~170 paid calls left the machine before anyone noticed.
        import daedalus.budget as B
        original = B.install_process_guard

        def refuse():
            raise RuntimeError("guard unavailable in this test")

        B.install_process_guard = refuse
        called: list[int] = []
        orig_call = F._one_call

        def spy(*a, **k):                     # pragma: no cover -- must not run
            called.append(1)
            return {}

        F._one_call = spy
        try:
            out = F.fan_out([F.FanoutTask(task_id="x", objective="q")],
                            Path(tempfile.mkdtemp()), concurrency=1)
        finally:
            B.install_process_guard = original
            F._one_call = orig_call
        self.assertEqual(out["state"], "refused")
        self.assertIn("could not be capped", out["reason"])
        self.assertEqual(out["paid_calls"], 0)
        self.assertEqual(called, [], "not one call may leave without the guard")


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
