"""Phase 2 regression coverage for the role-category taxonomy's integration
seams: the Mission Control dashboard, the per-repo override round-trip, and
queue_task's best-effort category stamping.

Kept separate from tests/test_categories.py (which pins categories.py's own
unit contract) so this file can own the cross-module wiring: core.get_dashboard,
the on-disk override file, and queue_task's interaction with router.route_task
and file_bridge.enqueue. Everything that could touch the network, a real
Ollama server, or the real outbox/bus is mocked, so the suite is deterministic
and hermetic on any box.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus.orchestration import categories as cats
from daedalus import core


class DashboardCarriesCategoriesTest(unittest.TestCase):
    """Mirrors tests/test_mission_control.py's DashboardContractTest setup:
    no real projects, no _process_rows, no live Ollama -- so get_dashboard(None)
    is fully offline-deterministic."""

    def setUp(self) -> None:
        patchers = [
            mock.patch("daedalus.core.list_projects", return_value=[]),
            mock.patch("daedalus.core._process_rows", return_value=[]),
            mock.patch("urllib.request.urlopen", side_effect=OSError("refused")),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_dashboard_includes_categories_joined_with_agents(self) -> None:
        dashboard = core.get_dashboard(None)
        self.assertIn("categories", dashboard)
        rows = dashboard["categories"]
        self.assertIsInstance(rows, list)
        self.assertTrue(rows, "expected at least one seeded category")

        hardware = next(c for c in rows if c["id"] == "hardware")
        self.assertIn("hardware-dev", [a["name"] for a in hardware["agents"]])
        self.assertEqual(hardware["count"], len(hardware["agents"]))

        # Pin the shape for every row, not just the one we inspect closely.
        for row in rows:
            self.assertIn("agents", row)
            self.assertIsInstance(row["agents"], list)
            self.assertIn("count", row)
            self.assertEqual(row["count"], len(row["agents"]))

    def test_dashboard_categories_match_get_categories_directly(self) -> None:
        # The dashboard's categories block is get_categories(selected)'s rows,
        # not a separate re-derivation -- pin that the two stay identical.
        dashboard = core.get_dashboard(None)
        direct = core.get_categories(None)
        self.assertEqual(dashboard["categories"], direct["categories"])


class CategoryOverrideRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name

    def test_update_writes_per_repo_override_and_does_not_leak_into_global(self) -> None:
        global_before = cats.get("implementation", None)
        self.assertIsNotNone(global_before)

        written_path = cats.update(
            "implementation", {"color": "#abcdef", "icon": "X"}, self.repo
        )

        # The override lands under <repo>/.agentenv/categories.json, never the
        # shipped global file.
        expected_path = Path(self.repo) / ".agentenv" / "categories.json"
        self.assertEqual(Path(written_path), expected_path)
        self.assertTrue(expected_path.exists())
        on_disk = json.loads(expected_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk[0]["id"], "implementation")
        self.assertEqual(on_disk[0]["color"], "#abcdef")
        self.assertEqual(on_disk[0]["icon"], "X")

        # Reloading with the repo_root picks up the recolor/re-icon.
        reloaded = cats.load(self.repo)
        implementation = next(c for c in reloaded if c["id"] == "implementation")
        self.assertEqual(implementation["color"], "#abcdef")
        self.assertEqual(implementation["icon"], "X")

        # The shipped global seed (repo_root=None) must be byte-for-byte
        # unchanged -- no leak from the per-repo override.
        global_after = cats.get("implementation", None)
        self.assertEqual(global_after, global_before)
        self.assertNotEqual(global_after["color"], "#abcdef")
        self.assertNotEqual(global_after["icon"], "X")


class QueueTaskCategoryStampTest(unittest.TestCase):
    """queue_task tags the payload with a routed agent's category as
    best-effort metadata -- it must never be able to change the lane the
    caller/policy already decided."""

    def setUp(self) -> None:
        patchers = [
            mock.patch("daedalus.core.resolve_repo_root", return_value="/fake/repo"),
            mock.patch(
                "daedalus.router.route_task",
                return_value={"name": "hardware-dev", "category": "hardware"},
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_queue_task_stamps_category_without_altering_requested_lane(self) -> None:
        captured: dict = {}

        def _fake_enqueue(objective, repo_root, paths, **kwargs):
            captured["objective"] = objective
            captured["repo_root"] = repo_root
            captured["paths"] = paths
            captured.update(kwargs)
            return Path("/fake/outbox/task.json")

        with mock.patch("daedalus.file_bridge.enqueue", side_effect=_fake_enqueue):
            result = core.queue_task(
                "proj", "wire up the fpga bench", lane="claude",
                source="test", strategy="single", paths=["hw/board.py"],
            )

        # The category came from the mocked route_task's owning agent.
        self.assertEqual(result["category"], "hardware")
        self.assertEqual(captured["category"], "hardware")

        # The lane is exactly what was requested -- category is metadata
        # only and never touches the lane decision.
        self.assertEqual(result["lane"], "claude")
        self.assertEqual(captured["lane"], "claude")

    def test_queue_task_falls_back_to_empty_category_when_routing_fails(self) -> None:
        captured: dict = {}

        def _fake_enqueue(objective, repo_root, paths, **kwargs):
            captured.update(kwargs)
            return Path("/fake/outbox/task.json")

        with mock.patch("daedalus.router.route_task", side_effect=RuntimeError("no agents configured")), \
             mock.patch("daedalus.file_bridge.enqueue", side_effect=_fake_enqueue):
            result = core.queue_task(
                "proj", "objective with no matching agent", lane="local_only",
                source="test", strategy="single", paths=[],
            )

        self.assertEqual(result["category"], "")
        # queue_task still passes category="" through to enqueue()'s kwargs
        # (file_bridge.enqueue itself is the one that only writes it into the
        # payload when truthy) -- what matters here is the lane is untouched
        # and no exception from the failed routing attempt escapes queue_task.
        self.assertEqual(captured["category"], "")
        self.assertEqual(result["lane"], "local_only")


if __name__ == "__main__":
    unittest.main()
