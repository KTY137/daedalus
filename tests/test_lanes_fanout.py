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


def _answer(task, vote, repo_root, model, timeout_s, brief, *_, **__):
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

        def counting(task, vote, repo_root, model, timeout_s, brief, *_, **__):
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
        out = F.fan_out([task], self.dir, concurrency=1, temperature=0.8)
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
        out = F.fan_out([task], self.dir, concurrency=1, temperature=0.8)
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

        def flaky(task, vote, repo_root, model, timeout_s, brief, *_, **__):
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
        out = F.fan_out([task], self.dir, concurrency=2, temperature=0.8)
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
        out = F.fan_out(tasks, self.dir, concurrency=4, temperature=0.8)
        self.assertEqual(out["tasks"], 4)
        self.assertEqual(out["paid_calls"], 12)


class TheGraphBriefIsInjected(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig = F._one_call
        self.briefs: list[str] = []

        def capture(task, vote, repo_root, model, timeout_s, brief, *_, **__):
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


class FakeCorroborationIsRefused(unittest.TestCase):
    """votes>1 at temperature 0.0 is one answer counted N times.

    MEASURED 2026-07-30. The decode temperature defaulted to 0.0 and every caller
    inherited it, so a task asking the same question three "independent" times
    got three identical answers -- and three copies of one answer are
    indistinguishable from three agreeing agents in every downstream consumer.

    This module's docstring calls votes "the point, not a feature", which made the
    claim worse than the bug: the corroboration was load-bearing in the
    documentation and absent in the decode.

    Refused at the door rather than warned about, because the alternative is a
    dataset that looks corroborated and has to be discarded after someone builds
    on it.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig = F._one_call
        self.temps: list[float] = []

        def capture(task, vote, repo_root, model, timeout_s, brief, *args, **kw):
            self.temps.append(kw.get("temperature", args[1] if len(args) > 1 else None))
            return _answer(task, vote, repo_root, model, timeout_s, brief)

        F._one_call = capture

    def tearDown(self):
        F._one_call = self._orig

    def test_votes_at_zero_temperature_is_refused_and_costs_nothing(self):
        task = F.FanoutTask(task_id="v", objective="q", votes=3)
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["state"], "refused")
        self.assertIn("temperature 0.0", out["reason"])
        self.assertEqual(out["paid_calls"], 0)
        self.assertEqual(self.temps, [], "not one call may leave")

    def test_the_refusal_names_how_many_tasks_are_affected(self):
        tasks = [F.FanoutTask(task_id=f"t{i}", objective="q", votes=3)
                 for i in range(4)]
        tasks.append(F.FanoutTask(task_id="single", objective="q", votes=1))
        out = F.fan_out(tasks, self.dir, concurrency=1)
        self.assertEqual(out["state"], "refused")
        self.assertIn("4 task(s)", out["reason"])

    def test_a_single_vote_at_zero_temperature_is_fine(self):
        # One deterministic opinion is honest. It is only the CLAIM of
        # independence that the temperature makes false.
        task = F.FanoutTask(task_id="s", objective="q", votes=1)
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["state"], "ran")
        self.assertEqual(out["paid_calls"], 1)

    def test_votes_with_a_real_temperature_runs(self):
        task = F.FanoutTask(task_id="v", objective="q", votes=3)
        out = F.fan_out([task], self.dir, concurrency=1, temperature=0.8)
        self.assertEqual(out["state"], "ran")
        self.assertEqual(out["paid_calls"], 3)

    def test_the_refusal_shape_matches_a_completed_run(self):
        # Same reasoning as the budget-guard refusal: a consumer must not need
        # two code paths, and the one it will forget is the refusal.
        task = F.FanoutTask(task_id="v", objective="q", votes=2)
        refused = F.fan_out([task], self.dir, concurrency=1)
        ran = F.fan_out([F.FanoutTask(task_id="o", objective="q")], self.dir,
                        concurrency=1)
        self.assertEqual(set(refused), set(ran) | {"reason"})


class ResultsCarryTheirRun(unittest.TestCase):
    """A paid call and its answer must join to the run that spent the money.

    Caught by the drift detector in tests/test_envelope_coverage.py on
    2026-07-30, which flagged this module as a record producer declaring neither
    conversion nor a reason -- correctly: these files were a new island whose
    records joined to nothing.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._orig = F._one_call
        F._one_call = _answer

    def tearDown(self):
        F._one_call = self._orig

    def test_a_fresh_result_carries_the_trace_in_scope(self):
        from daedalus.spine import envelope
        with envelope.trace_context("t-abc123"):
            out = F.fan_out([F.FanoutTask(task_id="x", objective="q")],
                            self.dir, concurrency=1)
        self.assertEqual(out["results"][0]["trace_id"], "t-abc123")
        # And on disk, not only in the return value.
        landed = json.loads((self.dir / f"{out['results'][0]['key']}.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(landed["trace_id"], "t-abc123")

    def test_no_trace_in_scope_is_None_and_never_a_minted_id(self):
        # current_trace_id never mints. A fresh unrelated id per record would make
        # the field 100% populated and every join return exactly one row.
        out = F.fan_out([F.FanoutTask(task_id="y", objective="q")],
                        self.dir, concurrency=1)
        self.assertIsNone(out["results"][0]["trace_id"])

    def test_a_resumed_result_keeps_the_trace_of_the_run_that_paid(self):
        from daedalus.spine import envelope
        task = F.FanoutTask(task_id="z", objective="q")
        with envelope.trace_context("run-one"):
            F.fan_out([task], self.dir, concurrency=1)
        with envelope.trace_context("run-two"):
            out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["resumed"], 1)
        self.assertEqual(out["paid_calls"], 0)
        self.assertEqual(
            out["results"][0]["trace_id"], "run-one",
            "a resumed answer must keep the trace of the run that PAID for it -- "
            "re-stamping it claims this run produced what it read off disk")


class BlockedIsNotAudited(unittest.TestCase):
    """A refusal is not evidence.

    Measured 2026-07-31 on the claims123 review tier: 6 of 6 units came back
    ``report.status == "blocked"``, the summary said ``ok=6``, and resume
    would have served the refusals into every later run as if they had been
    audited. These tests hold the two halves of the fix: refusals are counted
    apart from evidence, and an all-blocked persisted result is retried.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

        def stub(task, vote, repo_root, model, timeout_s, brief, *_, **__):
            status = "blocked" if task.task_id.startswith("ref") else "needs_review"
            return {"vote": vote, "provider": "stub", "persona": None,
                    "report": {"status": status, "summary": "s",
                               "files_changed": [], "tests_run": [],
                               "risks": [], "todos": [], "handoff": {}}}

        self._orig = F._one_call
        F._one_call = stub

    def tearDown(self):
        F._one_call = self._orig

    def test_blocked_is_counted_apart_from_ok(self):
        tasks = [F.FanoutTask(task_id="refused", objective="q"),
                 F.FanoutTask(task_id="healthy", objective="q")]
        out = F.fan_out(tasks, self.dir, concurrency=1)
        self.assertEqual(out["ok"], 1)
        self.assertEqual(out["blocked"], 1)
        self.assertEqual(out["failed"], 0)

    def test_a_persisted_all_blocked_result_is_retried_not_served(self):
        # The cause of a refusal may be a since-fixed parser or a transient
        # transport failure; serving it forever makes it permanent.
        task = F.FanoutTask(task_id="healthy-now", objective="q")
        (self.dir / f"{task.key}.json").write_text(json.dumps({
            "task_id": task.task_id, "votes_requested": 1,
            "answers": [{"vote": 1, "report": {"status": "blocked",
                                               "summary": "refused"}}]}),
            encoding="utf-8")
        out = F.fan_out([task], self.dir, concurrency=1)
        self.assertEqual(out["paid_calls"], 1)
        self.assertEqual(out["resumed"], 0)
        self.assertEqual(out["ok"], 1)

    def test_a_partially_blocked_result_is_still_served(self):
        # Partial evidence is evidence: one healthy vote makes the unit
        # servable, and the refusal beside it stays inspectable on disk.
        task = F.FanoutTask(task_id="mixed", objective="q", votes=2)
        (self.dir / f"{task.key}.json").write_text(json.dumps({
            "task_id": "mixed", "votes_requested": 2,
            "answers": [
                {"vote": 1, "report": {"status": "blocked", "summary": "no"}},
                {"vote": 2, "report": {"status": "needs_review",
                                       "summary": "yes"}},
            ]}), encoding="utf-8")
        out = F.fan_out([task], self.dir, concurrency=1, temperature=0.8)
        self.assertEqual(out["paid_calls"], 0)
        self.assertEqual(out["resumed"], 1)
        self.assertEqual(out["ok"], 1)
        self.assertEqual(out["blocked"], 0)

    def test_blocked_property_semantics(self):
        res = F.FanoutResult(task_id="t", key="k", votes_requested=1)
        # No answers is a failure to answer, not a refusal.
        self.assertFalse(res.blocked)
        res.answers.append({"report": {"status": "blocked"}})
        self.assertTrue(res.blocked)
        res.answers.append({"report": {"status": "done"}})
        self.assertFalse(res.blocked)
