"""Parallel dispatch remains read-only until Forge workcells exist.

Declared paths are routing hints, not an enforceable write boundary.  These
tests pin the conservative contract: writable tasks run sequentially with
whole-repo attribution even when their hints are disjoint.
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.kairos.scheduler import KairosScheduler, _paths_overlap
from daedalus.offload import _offload_impl

_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False}


def _internal_offload(*args, **kwargs):
    """Keep this scheduler-concurrency unit focused below the lease seam."""
    repo_root = kwargs.get("repo_root")
    if repo_root is None and len(args) > 1:
        repo_root = args[1]
    kwargs.setdefault("_attempt_workspace", {"worktree": str(repo_root)})
    return _offload_impl(*args, **kwargs)



def _report(files_changed):
    return {"status": "done", "summary": "s", "files_changed": files_changed,
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


def _make_repo(tmp: str, agents: list[dict]) -> str:
    cfg = Path(tmp) / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["src/", ".md"]}}', encoding="utf-8")
    for a in agents:
        (cfg / "agents" / f"{a['name']}.json").write_text(json.dumps(a), encoding="utf-8")
    return tmp


def _agent(name, path):
    return {"name": name, "call_name": name.title(), "model_tier": "haiku",
            "external_ok": True, "owns": [path], "triggers": ["greeting", "string", "helper"],
            "must_read": [], "output_schema": "agent_report_v1", "category": "implementation"}


class ParallelDispatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_overlap_detection(self):
        class A:
            def __init__(self, mode, paths): self.mode = mode; self.paths = paths
        self.assertTrue(_paths_overlap([A("write", ["src/a.py"]), A("write", ["src/a.py"])]))
        self.assertFalse(_paths_overlap([A("write", ["src/a.py"]), A("write", ["src/b.py"])]))
        self.assertFalse(_paths_overlap([A("advisory", ["src/a.py"]), A("advisory", ["src/a.py"])]))

    def test_live_dispatch_without_effect_capability_fails_before_provider(self):
        repo = _make_repo(self._tmp.name, [_agent("alpha", "src/a.py")])
        tasks = [{"objective": "Fix the greeting string in the helper",
                  "paths": ["src/a.py"]}]
        scheduler = KairosScheduler(availability=_AVAIL, active_agents=["alpha"])
        with mock.patch("daedalus.providers.get_provider") as provider:
            rows = scheduler.dispatch(repo, tasks, dry_run=False)
        provider.assert_not_called()
        self.assertEqual(rows[0]["status"], "effect_lease_required")
        self.assertEqual(rows[0]["wrote"], [])
        self.assertFalse((Path(repo) / "src/a.py").exists())

    def test_disjoint_write_tasks_stay_sequential_with_correct_attribution(self):
        repo = _make_repo(self._tmp.name, [_agent("alpha", "src/a.py"), _agent("beta", "src/b.py")])
        tasks = [{"objective": "Fix the greeting string in the helper", "paths": ["src/a.py"]},
                 {"objective": "Fix the greeting string in the helper", "paths": ["src/b.py"]}]

        _PathAwareWorker.reset()
        ik = KairosScheduler(max_workers=4, availability=_AVAIL,
                    active_agents=["alpha", "beta"])
        with mock.patch("daedalus.offload.offload", side_effect=_internal_offload), \
             mock.patch("daedalus.providers.get_provider",
                        side_effect=lambda n: _PathAwareWorker(repo)):
            rows = ik.dispatch(repo, tasks, dry_run=False, parallel=True)

        live = [r for r in rows if r.get("status") not in ("note",)]
        self.assertEqual(len(live), 2)
        for r in live:
            self.assertEqual(r["status"], "offloaded", r)
            # per-task attribution: each wrote EXACTLY its own path, not the sibling's
            self.assertEqual(r["wrote"], r["paths"], f"cross-attribution: {r}")
        self.assertEqual(_PathAwareWorker.max_concurrent, 1)
        self.assertTrue(any(r.get("status") == "note" for r in rows))

    def test_overlapping_write_tasks_fall_back_to_sequential(self):
        repo = _make_repo(self._tmp.name, [_agent("alpha", "src/a.py")])
        tasks = [{"objective": "Fix the greeting string in the helper", "paths": ["src/a.py"]},
                 {"objective": "Fix the greeting string in the helper", "paths": ["src/a.py"]}]
        with mock.patch("daedalus.offload.offload", side_effect=_internal_offload), \
             mock.patch("daedalus.providers.get_provider",
                        side_effect=lambda n: _PathAwareWorker(repo)):
            rows = KairosScheduler(max_workers=4, availability=_AVAIL, active_agents=["alpha"]) \
                .dispatch(repo, tasks, dry_run=False, parallel=True)
        self.assertTrue(any(r.get("status") == "note" for r in rows),
                        "expected a 'ran sequentially' note for writable work")


class _PathAwareWorker:
    """Writes whatever file it's told to via the run() paths kwarg (mirrors the
    rewrite path). Tracks how many workers are inside run() at once so a test
    can prove real concurrency deterministically."""
    _lock = threading.Lock()
    _active = 0
    max_concurrent = 0

    @classmethod
    def reset(cls):
        cls._active = 0
        cls.max_concurrent = 0

    def __init__(self, repo_root):
        self._repo = repo_root

    def run(self, *, paths, **kwargs):
        with _PathAwareWorker._lock:
            _PathAwareWorker._active += 1
            _PathAwareWorker.max_concurrent = max(_PathAwareWorker.max_concurrent,
                                                  _PathAwareWorker._active)
        time.sleep(0.2)   # hold the window open so a sibling can overlap
        rel = paths[0]
        p = Path(self._repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f'"""{rel}."""\nx = 1\n', encoding="utf-8")
        with _PathAwareWorker._lock:
            _PathAwareWorker._active -= 1
        return {"report": _report([rel])}

    def rollback(self):
        return []


if __name__ == "__main__":
    unittest.main()
