"""Offline tests for the build-session abstraction + wave planning
(``daedalus.build``). Every model/routing seam is patched -- no live Ollama,
no network, no real agent-role files needed. Run with:

    python -m unittest tests.test_build -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from daedalus import build
from daedalus.build import (
    BuildSession,
    assign_builder,
    load_session,
    plan_build,
)

# A fixed feature breakdown: two implementation subtasks (frontier) plus a
# docs, a tests, and a hardware subtask (all local-bench lanes).
_SUBTASKS = [
    {"objective": "Implement the parser core", "paths": ["parser.py"]},
    {"objective": "Write docs for the parser", "paths": ["README.md"]},
    {"objective": "Add unit tests for the parser", "paths": ["tests/test_parser.py"]},
    {"objective": "Implement the emitter", "paths": ["emitter.py"]},
    {"objective": "Wire the hardware bridge", "paths": ["hw.py"]},
]

# objective keyword -> owning agent (as router.route_task would return).
_ROUTES = {
    "Implement the parser core": {"name": "core-dev", "category": "implementation"},
    "Write docs for the parser": {"name": "docs-dev", "category": "docs"},
    "Add unit tests for the parser": {"name": "test-dev", "category": "tests"},
    "Implement the emitter": {"name": "core-dev", "category": "implementation"},
    "Wire the hardware bridge": {"name": "hardware-dev", "category": "hardware"},
}

# category -> {lane, tier} preset (as categories.preset_for would return).
_PRESETS = {
    "implementation": {"lane": "claude", "tier": "opus"},     # frontier
    "docs": {"lane": "local", "tier": "sonnet"},              # local bench
    "tests": {"lane": "local", "tier": "sonnet"},             # local bench
    "hardware": {"lane": "local_only", "tier": "opus"},       # local bench
}


def _fake_route(objective, paths=None, repo_root=None, active_agents=None):
    return _ROUTES[objective]


def _fake_preset(agent, repo_root=None):
    return _PRESETS[agent["category"]]


@contextmanager
def _patched(subtasks=_SUBTASKS):
    # bookkeeper.update is patched so no build test can regenerate the REAL
    # docs/architecture.html (+ history snapshot) as a side effect of save().
    with patch.object(build, "decompose", return_value=list(subtasks)), \
            patch.object(build, "route_task", side_effect=_fake_route), \
            patch.object(build, "preset_for", side_effect=_fake_preset), \
            patch("daedalus.bookkeeper.update", return_value=None) as bk:
        yield bk


class AssignBuilderTests(unittest.TestCase):
    def test_local_lanes_stay_on_the_bench(self):
        self.assertEqual(assign_builder("local"), (build.LOCAL_BUILDER, False))
        self.assertEqual(assign_builder("local_only"), (build.LOCAL_BUILDER, False))

    def test_claude_and_auto_lanes_go_frontier(self):
        self.assertEqual(assign_builder("claude"), (build.FRONTIER_BUILDER, True))
        # Frontier-first: an unresolved 'auto' lane escalates to the builder crew.
        self.assertEqual(assign_builder("auto"), (build.FRONTIER_BUILDER, True))


class PlanBuildShapeTests(unittest.TestCase):
    def test_produces_bounded_waves(self):
        with tempfile.TemporaryDirectory() as d, _patched():
            session = plan_build("Add a config parser", "/repo", runs_dir=d)
        # 5 subtasks, default max_workers=3 -> two waves (3 + 2).
        self.assertEqual(session.max_workers, 3)
        self.assertEqual(len(session.waves), 2)
        self.assertEqual([len(w.tasks) for w in session.waves], [3, 2])
        self.assertEqual([w.index for w in session.waves], [0, 1])
        self.assertEqual(len(session.tasks()), 5)

    def test_each_task_carries_owner_category_lane_tier(self):
        with tempfile.TemporaryDirectory() as d, _patched():
            session = plan_build("Add a config parser", "/repo", runs_dir=d)
        by_obj = {t.objective: t for t in session.tasks()}
        core = by_obj["Implement the parser core"]
        self.assertEqual(core.agent, "core-dev")
        self.assertEqual(core.category, "implementation")
        self.assertEqual(core.lane, "claude")
        self.assertEqual(core.tier, "opus")
        docs = by_obj["Write docs for the parser"]
        self.assertEqual(docs.agent, "docs-dev")
        self.assertEqual((docs.category, docs.lane, docs.tier), ("docs", "local", "sonnet"))

    def test_frontier_vs_local_follows_the_category_lane(self):
        with tempfile.TemporaryDirectory() as d, _patched():
            session = plan_build("Add a config parser", "/repo", runs_dir=d)
        by_obj = {t.objective: t for t in session.tasks()}
        # implementation (lane=claude) -> frontier builder
        for obj in ("Implement the parser core", "Implement the emitter"):
            self.assertTrue(by_obj[obj].frontier)
            self.assertEqual(by_obj[obj].builder, build.FRONTIER_BUILDER)
        # docs/tests/hardware (local lanes) -> local bench
        for obj in ("Write docs for the parser", "Add unit tests for the parser",
                    "Wire the hardware bridge"):
            self.assertFalse(by_obj[obj].frontier)
            self.assertEqual(by_obj[obj].builder, build.LOCAL_BUILDER)
        self.assertEqual(session.summary(),
                         {"subtasks": 5, "waves": 2, "frontier": 2, "local": 3})


class RoundTripTests(unittest.TestCase):
    def test_to_dict_from_dict_round_trips(self):
        with tempfile.TemporaryDirectory() as d, _patched():
            session = plan_build("Add a config parser", "/repo",
                                 project=None, runs_dir=d, persist=False)
        restored = BuildSession.from_dict(session.to_dict())
        self.assertEqual(restored.to_dict(), session.to_dict())
        self.assertEqual(restored.feature, session.feature)
        self.assertEqual([t.to_dict() for t in restored.tasks()],
                         [t.to_dict() for t in session.tasks()])

    def test_persistence_round_trips_from_disk(self):
        with tempfile.TemporaryDirectory() as d, _patched():
            session = plan_build("Add a config parser", "/repo", runs_dir=d)
            self.assertIsNotNone(session.snapshot_path)
            snap = Path(session.snapshot_path)
            self.assertTrue(snap.exists())
            self.assertTrue(str(snap).startswith(str(Path(d))))
            # Slug + directory follow the runs/build convention.
            self.assertTrue(snap.name.startswith("add-a-config-parser-"))
            on_disk = json.loads(snap.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["feature"], "Add a config parser")
            reloaded = load_session(snap)
        self.assertEqual(reloaded.to_dict(), session.to_dict())
        self.assertEqual(len(reloaded.waves), 2)

    def test_persist_false_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d, _patched():
            session = plan_build("Add a config parser", "/repo",
                                 runs_dir=d, persist=False)
            self.assertIsNone(session.snapshot_path)
            self.assertEqual(list(Path(d).glob("*.json")), [])


class SingleSubtaskTests(unittest.TestCase):
    def test_single_subtask_is_one_wave(self):
        one = [{"objective": "Implement the parser core", "paths": ["parser.py"]}]
        with tempfile.TemporaryDirectory() as d, _patched(subtasks=one):
            session = plan_build("Tiny feature", "/repo", runs_dir=d)
        self.assertEqual(len(session.waves), 1)
        self.assertEqual(len(session.waves[0].tasks), 1)
        self.assertTrue(session.waves[0].tasks[0].frontier)


class BookkeeperIsolationTests(unittest.TestCase):
    """plan_build's persist path must not touch the real architecture artifact
    unless asked to (regression: the suite used to rewrite docs/architecture.html)."""

    def test_update_architecture_false_skips_bookkeeper(self):
        with tempfile.TemporaryDirectory() as d, _patched() as bk:
            plan_build("Add a config parser", "/repo", runs_dir=d,
                       update_architecture=False)
            bk.assert_not_called()

    def test_persist_default_forwards_to_bookkeeper(self):
        with tempfile.TemporaryDirectory() as d, _patched() as bk:
            plan_build("Add a config parser", "/repo", runs_dir=d)
            bk.assert_called_once()


if __name__ == "__main__":
    unittest.main()
