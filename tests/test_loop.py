"""Tests for daedalus/loop.py -- the loop driver.

Written by Theseus (orchestration-dev) to scratchpad; tests/ is owned by Talos.
Move to tests/test_loop.py as-is.

Covers, in the order the brief ranked them:
  1. the stop  -- killswitch honored between iterations AND passed into the wave
  2. the bounds -- iterations / wall clock / spend, each ALONE sufficient
  3. governance -- red means run-but-promote-nothing, and say so
  4. convergence -- a repeatedly-failing candidate stops being re-picked, visibly
  5. observability -- events land in the progress log while the loop runs

Every test drives LoopDriver with a FAKE executor. That is deliberate: the real
path spends money and needs a git repo, and none of the properties above are
properties of the wave executor -- they are properties of the loop around it.
The one place the real executor matters (does run_wave actually forward
`cancel`?) is asserted structurally, against the live signature, in
test_seam_forwards_cancel_to_real_chain.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest import mock

from daedalus import loop as loopmod
from daedalus.loop import (
    LoopBounds, LoopDriver, LoopLedger, LoopMisconfigured, _Spend, _path_key,
)


# --------------------------------------------------------------------------- #
# fakes                                                                        #
# --------------------------------------------------------------------------- #
class FakeWaveResult:
    def __init__(self, results):
        self.results = results


class FakeExecutor:
    """Records every run_wave call and returns a scripted result."""

    def __init__(self, script=None, on_call=None):
        self.availability = {}
        self.calls = []
        self.script = list(script or [])
        self.on_call = on_call

    def run_wave(self, scheduler, wave, repo_root, *, dry_run=True,
                 parallel=True, cancel=None):
        self.calls.append({"dry_run": dry_run, "parallel": parallel,
                           "cancel": cancel, "wave": wave})
        if self.on_call is not None:
            self.on_call(len(self.calls))
        result = (self.script.pop(0) if self.script else
                  {"status": "gated_held", "attempt_state": "clean",
                   "task_id": "kairos-senior-deadbeef", "paths": []})
        return FakeWaveResult([result])


class FakeCandidate:
    def __init__(self, task_id, paths=(), score=100.0):
        self.task_id = task_id
        self.instruction = f"do {task_id}"
        self.source = "work_queue"
        self.score = score
        self.target_paths = tuple(paths)


def make_driver(tmp, *, candidates=None, script=None, bounds=None,
                dry_run=False, on_call=None, promotion_allowed=False,
                executor=None):
    """A LoopDriver with the picker, governance and session-builder stubbed."""
    ex = executor or FakeExecutor(script=script, on_call=on_call)
    d = LoopDriver(repo_root=str(tmp), bounds=bounds or LoopBounds(),
                   executor=ex, dry_run=dry_run, runs_dir=tmp / "runs")
    cands = list(candidates if candidates is not None
                 else [FakeCandidate("cand-1", ["a/b.py"])])
    d._session_for = lambda c: mock.MagicMock(waves=[mock.MagicMock()])
    d._pick_queue = cands
    return d, ex


def patch_env(driver, *, promotion_allowed=False, spend=0.0):
    """Patch the three external reads the loop makes: governance, picker, spend."""
    gov = {"promotion_allowed": promotion_allowed,
           "state": "working" if promotion_allowed else "degraded",
           "verdict": "discrimination receipt is stale"}
    queue = mock.MagicMock(candidates=driver._pick_queue)
    return (
        mock.patch("daedalus.core.get_governance", return_value=gov),
        mock.patch("daedalus.spine.picker.build_queue", return_value=queue),
        mock.patch.object(loopmod, "read_spend",
                          return_value=_Spend("2026-07", spend, True)),
        mock.patch("daedalus.kairos.scheduler.KairosScheduler",
                   return_value=mock.MagicMock(availability={}, max_workers=3)),
    )


def run_driver(driver, **kw):
    a, b, c, d = patch_env(driver, **kw)
    with a, b, c, d:
        return driver.run()


def spend_series(*readings):
    """A read_spend() stub that yields ``readings`` then repeats the last one.

    Never StopIteration: the loop reads spend a variable number of times (once
    per bound check, twice per iteration, once at teardown), and a fixture that
    ran dry would fail the test for a reason that has nothing to do with the
    property under test.
    """
    seq = list(readings)
    state = {"i": 0}

    def _next():
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[i]

    return _next


# --------------------------------------------------------------------------- #
# 1. THE STOP                                                                  #
# --------------------------------------------------------------------------- #
class TestTheStop(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_looptmp"
        self.tmp.mkdir(exist_ok=True)

    def test_unarmed_switch_stops_before_any_iteration(self):
        """FAIL CLOSED: no permit means the loop never spends at all."""
        d, ex = make_driver(self.tmp)
        d.switch.clear()  # no permit
        report = run_driver(d)
        self.assertEqual(report.stop_reason, "killswitch")
        self.assertEqual(len(report.iterations), 0)
        self.assertEqual(ex.calls, [], "an unarmed loop dispatched a wave")

    def test_stop_between_iterations_is_honored(self):
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=10),
            candidates=[FakeCandidate(f"c{i}", [f"f{i}.py"]) for i in range(10)],
            on_call=lambda n: d.switch.stop("test") if n == 2 else None)
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertEqual(report.stop_reason, "killswitch")
        self.assertEqual(len(ex.calls), 2,
                         "loop dispatched another wave after the stop")

    def test_cancel_token_is_passed_into_the_wave(self):
        """The token must reach run_wave, not just guard the outer loop."""
        d, ex = make_driver(self.tmp, bounds=LoopBounds(max_iterations=1))
        d.switch.arm(force=True)
        run_driver(d)
        self.assertIs(ex.calls[0]["cancel"], d.switch)

    def test_interrupted_iteration_is_not_counted_as_evidence(self):
        """A cancelled gate is indistinguishable from a failed one on this
        path, so its outcome must not enter the convergence ledger."""
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=3),
            script=[{"status": "write_gate_failed", "attempt_state": "gates_failed",
                     "task_id": "kairos-senior-1", "paths": []}],
            on_call=lambda n: d.switch.stop("mid-wave"))
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertEqual(len(report.iterations), 1)
        self.assertFalse(report.iterations[0].counted)
        self.assertEqual(d.ledger.n_attempts("cand-1"), 0,
                         "an interrupted attempt was recorded as evidence")
        self.assertTrue(any("NOT recorded as evidence" in n for n in report.notes))


# --------------------------------------------------------------------------- #
# 2. THE THREE BOUNDS, each alone sufficient                                   #
# --------------------------------------------------------------------------- #
class TestBounds(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_looptmp"
        self.tmp.mkdir(exist_ok=True)

    def test_no_bound_may_be_unlimited(self):
        for bad in ({"max_iterations": 0}, {"max_wall_clock_s": 0},
                    {"max_spend_usd": -1}, {"max_attempts_per_candidate": 0},
                    {"max_spend_usd": None}):
            with self.assertRaises(LoopMisconfigured, msg=f"accepted {bad}"):
                LoopBounds(**bad)

    def test_iteration_bound_alone_halts(self):
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=3,
                                        max_wall_clock_s=9999,
                                        max_spend_usd=9999),
            candidates=[FakeCandidate(f"c{i}", [f"f{i}.py"]) for i in range(50)])
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertEqual(report.stop_reason, "max_iterations")
        self.assertEqual(len(ex.calls), 3)

    def test_wall_clock_bound_alone_halts(self):
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=9999, max_wall_clock_s=0.3,
                                        max_spend_usd=9999),
            candidates=[FakeCandidate(f"c{i}", [f"f{i}.py"]) for i in range(500)],
            on_call=lambda n: time.sleep(0.2))
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertEqual(report.stop_reason, "max_wall_clock")
        self.assertLess(len(ex.calls), 500)

    def test_spend_bound_alone_halts(self):
        """Spend climbs past the ceiling; iterations and clock are wide open."""
        d, _ = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=9999, max_wall_clock_s=9999,
                                        max_spend_usd=1.0),
            candidates=[FakeCandidate(f"c{i}", [f"f{i}.py"]) for i in range(50)])
        d.switch.arm(force=True)
        spends = spend_series(*[_Spend("2026-07", v, True)
                                for v in (0.0, 0.4, 0.4, 0.9, 0.9, 1.5)])
        gov = {"promotion_allowed": False, "state": "degraded", "verdict": "x"}
        with mock.patch("daedalus.core.get_governance", return_value=gov), \
             mock.patch("daedalus.spine.picker.build_queue",
                        return_value=mock.MagicMock(candidates=d._pick_queue)), \
             mock.patch.object(loopmod, "read_spend", side_effect=spends), \
             mock.patch("daedalus.kairos.scheduler.KairosScheduler",
                        return_value=mock.MagicMock(availability={}, max_workers=3)):
            report = d.run()
        self.assertEqual(report.stop_reason, "max_spend")

    def test_unreadable_budget_ledger_stops_the_loop(self):
        """Cannot measure spend => cannot enforce the bound => must not spend."""
        d, ex = make_driver(self.tmp, bounds=LoopBounds(max_iterations=9))
        d.switch.arm(force=True)
        gov = {"promotion_allowed": False, "state": "degraded", "verdict": "x"}
        with mock.patch("daedalus.core.get_governance", return_value=gov), \
             mock.patch("daedalus.spine.picker.build_queue",
                        return_value=mock.MagicMock(candidates=d._pick_queue)), \
             mock.patch.object(loopmod, "read_spend",
                               return_value=_Spend("", 0.0, False, "disk on fire")), \
             mock.patch("daedalus.kairos.scheduler.KairosScheduler",
                        return_value=mock.MagicMock(availability={}, max_workers=3)):
            report = d.run()
        self.assertEqual(report.stop_reason, "max_spend")
        self.assertIn("unreadable", report.stop_detail)
        self.assertEqual(ex.calls, [])

    def test_budget_period_rollover_stops_rather_than_miscounting(self):
        d, _ = make_driver(self.tmp, bounds=LoopBounds(max_iterations=9))
        d.switch.arm(force=True)
        spends = spend_series(_Spend("2026-07", 5.0, True),
                              _Spend("2026-07", 5.0, True),
                              _Spend("2026-08", 0.0, True))
        gov = {"promotion_allowed": False, "state": "degraded", "verdict": "x"}
        with mock.patch("daedalus.core.get_governance", return_value=gov), \
             mock.patch("daedalus.spine.picker.build_queue",
                        return_value=mock.MagicMock(candidates=d._pick_queue)), \
             mock.patch.object(loopmod, "read_spend", side_effect=spends), \
             mock.patch("daedalus.kairos.scheduler.KairosScheduler",
                        return_value=mock.MagicMock(availability={}, max_workers=3)):
            report = d.run()
        self.assertEqual(report.stop_reason, "max_spend")
        self.assertIn("rolled over", report.stop_detail)

    def test_entry_point_installs_the_spend_guard(self):
        src = (Path(loopmod.__file__)).read_text(encoding="utf-8")
        self.assertIn("install_process_guard", src)
        self.assertIn('__name__ == "__main__"', src)


# --------------------------------------------------------------------------- #
# 3. GOVERNANCE: red = productive but inert, never "broken"                    #
# --------------------------------------------------------------------------- #
class TestGovernance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_looptmp"
        self.tmp.mkdir(exist_ok=True)

    def test_red_governance_still_runs_iterations(self):
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=2),
            candidates=[FakeCandidate(f"c{i}", [f"f{i}.py"]) for i in range(5)])
        d.switch.arm(force=True)
        report = run_driver(d, promotion_allowed=False)
        self.assertEqual(len(ex.calls), 2, "red governance stopped the loop")
        self.assertEqual(report.mode, "inert")
        self.assertEqual(report.promoted, 0)
        self.assertTrue(any("PRODUCTIVELY BUT INERTLY" in n for n in report.notes))

    def test_inert_run_still_reports_gated_clean_work(self):
        """The distinction that keeps an inert run from looking like a failure."""
        d, _ = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=1),
            script=[{"status": "gated_held", "attempt_state": "clean",
                     "task_id": "k-1", "paths": ["a/b.py"],
                     "reason": "held by governance"}])
        d.switch.arm(force=True)
        report = run_driver(d, promotion_allowed=False)
        self.assertEqual(report.gated_clean, 1)
        self.assertEqual(report.promoted, 0)

    def test_green_governance_reports_promoting_mode(self):
        d, _ = make_driver(self.tmp, bounds=LoopBounds(max_iterations=1))
        d.switch.arm(force=True)
        report = run_driver(d, promotion_allowed=True)
        self.assertEqual(report.mode, "promoting")


# --------------------------------------------------------------------------- #
# 4. CONVERGENCE                                                               #
# --------------------------------------------------------------------------- #
class TestConvergence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_looptmp"
        self.tmp.mkdir(exist_ok=True)

    def test_repeatedly_failing_candidate_stops_being_repicked(self):
        """THE headline failure mode: one candidate, always failing, and only
        the iteration bound between the loop and an empty wallet."""
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=20,
                                        max_attempts_per_candidate=2),
            candidates=[FakeCandidate("stuck", ["a/b.py"])],
            script=[{"status": "write_gate_failed", "attempt_state": "gates_failed",
                     "task_id": f"kairos-senior-{i}", "paths": ["a/b.py"]}
                    for i in range(20)])
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertEqual(len(ex.calls), 2,
                         "loop kept re-picking a candidate past its attempt bound")
        self.assertEqual(report.stop_reason, "queue_exhausted")

    def test_the_refusal_is_visible_not_silent(self):
        d, _ = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=20,
                                        max_attempts_per_candidate=1),
            candidates=[FakeCandidate("stuck", ["a/b.py"])],
            script=[{"status": "write_gate_failed", "attempt_state": "gates_failed",
                     "task_id": "k1", "paths": ["a/b.py"]}] * 5)
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertTrue(report.skipped, "a refused candidate left no trace")
        self.assertEqual(report.skipped[0]["candidate_id"], "stuck")
        self.assertIn("gates_failed", report.skipped[0]["reason"])

    def test_empty_queue_halts(self):
        d, ex = make_driver(self.tmp, candidates=[],
                            bounds=LoopBounds(max_iterations=9))
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertEqual(report.stop_reason, "queue_exhausted")
        self.assertEqual(ex.calls, [])

    def test_ledger_keeps_the_join_key_the_picker_cannot_compute(self):
        """attempt_memory looks up candidate ids; the gated path attempts under
        a fresh kairos-<lane>-<uuid>. The ledger must keep the bridge."""
        led = LoopLedger()
        led.record("cand-1", outcome="gates_failed", iteration=0,
                   attempt_task_ids=["kairos-senior-abc123"])
        self.assertEqual(led.attempts["cand-1"]["attempt_task_ids"],
                         [["kairos-senior-abc123"]])

    def test_path_claim_blocks_a_sibling_branch_collision(self):
        """Two candidates, same file. The second must not produce a second
        integration branch that a human cannot merge alongside the first."""
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=5),
            candidates=[FakeCandidate("c1", ["daedalus/x.py"]),
                        FakeCandidate("c2", ["daedalus/x.py"])],
            script=[{"status": "gated_promoted", "attempt_state": "clean",
                     "task_id": "k1", "changed_paths": ["daedalus/x.py"],
                     "integration_branch": "kairos-integration-aaa"}])
        d.switch.arm(force=True)
        report = run_driver(d, promotion_allowed=True)
        self.assertEqual(len(ex.calls), 1, "second candidate hit a claimed file")
        self.assertTrue(any("already claimed" in s["reason"]
                            for s in report.skipped))

    def test_claim_normalizes_separators_like_the_scheduler(self):
        led = LoopLedger()
        led.claim("c1", ["daedalus\\x.py"], iteration=0, basis="changed_paths")
        self.assertIsNotNone(led.claimed_by(["daedalus/x.py"]))
        self.assertEqual(_path_key("a\\b\\c.py"), "a/b/c.py")

    def test_failed_attempt_does_not_claim_its_paths(self):
        """A candidate that produced nothing must not lock the file away."""
        led = LoopLedger()
        d, ex = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=2),
            candidates=[FakeCandidate("c1", ["z.py"]), FakeCandidate("c2", ["z.py"])],
            script=[{"status": "write_gate_failed", "attempt_state": "gates_failed",
                     "task_id": "k1", "paths": ["z.py"]},
                    {"status": "gated_held", "attempt_state": "clean",
                     "task_id": "k2", "paths": ["z.py"]}])
        d.switch.arm(force=True)
        run_driver(d)
        self.assertEqual(len(ex.calls), 2,
                         "a failed attempt claimed its paths and blocked a retry")

    def test_sibling_branches_are_named_in_the_report(self):
        d, _ = make_driver(
            self.tmp, bounds=LoopBounds(max_iterations=2),
            candidates=[FakeCandidate("c1", ["p.py"]), FakeCandidate("c2", ["q.py"])],
            script=[{"status": "gated_promoted", "attempt_state": "clean",
                     "task_id": "k1", "changed_paths": ["p.py"],
                     "integration_branch": "kairos-integration-aaa"},
                    {"status": "gated_promoted", "attempt_state": "clean",
                     "task_id": "k2", "changed_paths": ["q.py"],
                     "integration_branch": "kairos-integration-bbb"}])
        d.switch.arm(force=True)
        report = run_driver(d, promotion_allowed=True)
        self.assertEqual(report.integration_branches,
                         ["kairos-integration-aaa", "kairos-integration-bbb"])
        self.assertTrue(any("SIBLINGS" in n for n in report.notes))


# --------------------------------------------------------------------------- #
# 5. OBSERVABILITY + dry run                                                    #
# --------------------------------------------------------------------------- #
class TestObservabilityAndDryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_looptmp"
        self.tmp.mkdir(exist_ok=True)

    def test_events_land_in_the_progress_log_under_the_candidate_id(self):
        from daedalus.progress import ProgressLog

        log = ProgressLog(self.tmp / "events.jsonl")
        d, _ = make_driver(self.tmp, bounds=LoopBounds(max_iterations=1))
        d._progress_log = log
        d.switch.arm(force=True)
        run_driver(d)
        kinds = [e["kind"] for e in
                 [json.loads(x) for x in
                  (self.tmp / "events.jsonl").read_text(encoding="utf-8").splitlines()
                  if x.strip()]]
        self.assertIn("QUEUED", [k.upper() for k in kinds])
        self.assertIn("CLAIMED", [k.upper() for k in kinds])

    def test_dry_run_spends_nothing_and_persists_nothing(self):
        d, ex = make_driver(self.tmp, dry_run=True,
                            bounds=LoopBounds(max_iterations=2),
                            candidates=[FakeCandidate("c1", ["a.py"]),
                                        FakeCandidate("c2", ["b.py"])])
        d.switch.arm(force=True)
        report = run_driver(d)
        self.assertTrue(all(c["dry_run"] for c in ex.calls))
        self.assertIsNone(d.ledger.path)
        self.assertIsNone(report.ledger_path)

    def test_report_json_round_trips(self):
        d, _ = make_driver(self.tmp, bounds=LoopBounds(max_iterations=1))
        d.switch.arm(force=True)
        report = run_driver(d)
        blob = json.dumps(report.to_dict())
        self.assertIn("stop_reason", json.loads(blob))
        self.assertIn(report.stop_reason, loopmod.STOP_REASONS)


# --------------------------------------------------------------------------- #
# the real seam                                                                #
# --------------------------------------------------------------------------- #
class TestRealSeam(unittest.TestCase):
    def test_seam_forwards_cancel_to_real_chain(self):
        """Asserted against the LIVE signatures, so it fails the day someone
        drops `cancel` from any link rather than the day a loop cannot stop."""
        import inspect

        from daedalus.build_exec import WaveExecutor, _accepts_cancel
        from daedalus.kairos import gated_writes as g

        self.assertIn("cancel",
                      inspect.signature(WaveExecutor.run_wave).parameters)
        for fn in (g.run_write_wave, g.gate_candidates, g._attempt_assignment,
                   g.promote_candidates, g._reattempt):
            self.assertIn("cancel", inspect.signature(fn).parameters,
                          f"{fn.__name__} dropped its cancel parameter")
        self.assertTrue(_accepts_cancel(g.run_write_wave))

    def test_run_wave_refuses_to_dispatch_when_already_cancelled(self):
        from daedalus.build_exec import WaveExecutor
        from daedalus.spine.killswitch import KillSwitch, LoopHalted

        sw = KillSwitch(Path(__file__).parent / "_looptmp" / "sw")
        sw.clear()  # unarmed == stopped
        ex = WaveExecutor()
        sched = mock.MagicMock()
        sched.accept.return_value = []
        wave = mock.MagicMock(index=0, tasks=[])
        with mock.patch("daedalus.build.wave_path_conflicts", return_value=[]):
            with self.assertRaises(LoopHalted):
                ex.run_wave(sched, wave, ".", dry_run=False, parallel=False,
                            cancel=sw)
        sched.dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
