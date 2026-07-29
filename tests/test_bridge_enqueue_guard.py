"""The outbox must refuse work when nothing is alive to consume it.

THE INCIDENT THIS PINS (MEASURED 2026-07-29):
    runs/bridge_heartbeat.json    last beat 2026-07-16T22:51:51Z, pid 9536 (dead)
    outbox/20260720T121142Z-...   enqueued  2026-07-20T12:11:42Z

The owner's own question -- "how is daedalus currently build and how does it
function?" -- was queued three and a half days after the only consumer had
died, and sat there for nine more. `enqueue` returned a Path. Every caller had
every reason to believe the work was queued. Nothing was ever going to run it.

These tests fail if that silence ever comes back.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus import file_bridge as fb  # noqa: E402


def _hb(state: str) -> dict:
    """A heartbeat_status() payload in the given state."""
    base = {"restart": "python -m daedalus.file_bridge watch --project demo",
            "age_s": 1.0, "pid": 123, "project": "demo"}
    if state == "none":
        return {"state": "none", "restart": base["restart"],
                "detail": "no heartbeat recorded"}
    if state == "stale":
        return {**base, "state": "stale", "age_s": 1066705.1}
    if state == "wedged":
        return {**base, "state": "wedged", "busy_for_s": 4000.0,
                "current": {"file": "stuck.json"}}
    if state == "busy":
        return {**base, "state": "busy", "busy_for_s": 12.0,
                "current": {"file": "running.json"}}
    return {**base, "state": "alive"}


class EnqueueRefusesWithoutAConsumer(unittest.TestCase):
    """The guard proper."""

    def setUp(self) -> None:
        # Never touch the real outbox.
        self._tmp = Path(__file__).resolve().parents[1] / "runs" / "_test_outbox_guard"
        self._tmp.mkdir(parents=True, exist_ok=True)
        for p in self._tmp.glob("*.json"):
            p.unlink()
        patcher = mock.patch.object(fb, "OUTBOX", self._tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        for p in self._tmp.glob("*"):
            p.unlink()
        self._tmp.rmdir()

    def _enqueue(self, **kw):
        return fb.enqueue("rebuild the index", repo_root=str(self._tmp),
                          paths=[], project="demo", **kw)

    def test_a_dead_watcher_refuses_the_enqueue(self):
        """state=stale -- the exact 2026-07-20 condition."""
        with mock.patch.object(fb, "heartbeat_status", return_value=_hb("stale")):
            with self.assertRaises(fb.WatcherNotRunning) as caught:
                self._enqueue()
        self.assertEqual(caught.exception.state, "stale")

    def test_no_watcher_at_all_refuses_the_enqueue(self):
        """state=none -- a fresh machine where the watcher was never started."""
        with mock.patch.object(fb, "heartbeat_status", return_value=_hb("none")):
            with self.assertRaises(fb.WatcherNotRunning):
                self._enqueue()

    def test_a_refusal_leaves_NO_file_behind(self):
        """The refusal must not invent a fourth queue state.

        If a refused enqueue still dropped the .json, a later watcher would
        pick up work its producer was told had been rejected.
        """
        with mock.patch.object(fb, "heartbeat_status", return_value=_hb("stale")):
            with self.assertRaises(fb.WatcherNotRunning):
                self._enqueue()
        self.assertEqual(list(self._tmp.glob("*.json")), [],
                         "a REFUSED enqueue wrote a request into the outbox anyway")
        self.assertEqual(list(self._tmp.glob("*.tmp")), [],
                         "a refused enqueue left its atomic-publish temp file behind")

    def test_the_refusal_says_how_to_fix_it(self):
        """An error that does not carry the remedy just relocates the problem."""
        with mock.patch.object(fb, "heartbeat_status", return_value=_hb("stale")):
            with self.assertRaises(fb.WatcherNotRunning) as caught:
                self._enqueue()
        msg = str(caught.exception)
        self.assertIn("python -m daedalus.file_bridge watch", msg,
                      "the refusal does not name the command that starts a consumer")
        self.assertIn("require_watcher=False", msg,
                      "the refusal does not name its own escape hatch")
        self.assertIn("1066705.1", msg, "the refusal does not say HOW stale")

    def test_a_live_watcher_enqueues_normally(self):
        """The guard must not become a wall. alive/busy both have a consumer."""
        for state in ("alive", "busy"):
            with self.subTest(state=state):
                with mock.patch.object(fb, "heartbeat_status", return_value=_hb(state)):
                    path = self._enqueue()
                self.assertTrue(path.exists())
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(payload["objective"], "rebuild the index")
                path.unlink()

    def test_a_wedged_watcher_warns_but_still_accepts(self):
        """A wedged watcher IS a consumer -- slow, not absent.

        Refusing here would be the five-states-collapse in the other
        direction: treating 'degraded' as 'absent'.
        """
        with mock.patch.object(fb, "heartbeat_status", return_value=_hb("wedged")):
            with mock.patch("sys.stderr") as err:
                path = self._enqueue()
        self.assertTrue(path.exists())
        written = "".join(str(c.args[0]) for c in err.write.call_args_list if c.args)
        self.assertIn("WEDGED", written, "a wedged watcher enqueued in silence")

    def test_force_queues_ahead_deliberately_and_still_warns(self):
        """The escape hatch works, and is not silent."""
        with mock.patch.object(fb, "heartbeat_status", return_value=_hb("stale")):
            with mock.patch("sys.stderr") as err:
                path = self._enqueue(require_watcher=False)
        self.assertTrue(path.exists(), "require_watcher=False must still queue")
        written = "".join(str(c.args[0]) for c in err.write.call_args_list if c.args)
        self.assertIn("NO live watcher", written,
                      "a deliberate dead-queue enqueue happened silently")


class TheRealHeartbeatStillClassifiesTheRealIncident(unittest.TestCase):
    """Not a mock: the actual stale-detection arithmetic."""

    def test_the_2026_07_16_heartbeat_reads_as_stale_today(self):
        payload = {"ts": "2026-07-16T22:51:51+00:00", "epoch": 1784242311.3270998,
                   "pid": 9536, "project": "project_tct", "current": None}
        tmp = Path(__file__).resolve().parents[1] / "runs" / "_test_hb_guard.json"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        try:
            with mock.patch.object(fb, "HEARTBEAT_PATH", tmp):
                # 2026-07-20T12:11:42Z -- the moment the owner's task was queued.
                hb = fb.heartbeat_status(now=1784556702.0)
        finally:
            tmp.unlink()
        self.assertEqual(hb["state"], "stale",
                         "the watcher was already dead when the task was queued, "
                         "and the bridge must say so")
        self.assertGreater(hb["age_s"], 300000.0)


if __name__ == "__main__":
    unittest.main()
