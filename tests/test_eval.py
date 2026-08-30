"""Tier-1 tests for the distillation eval harness (deterministic, no LLM).

Asserts: recall is a fraction in [0,1], mean compression is positive, the
report structure is well-formed and ASCII-safe, and the miss-detection path
actually surfaces a dropped symbol. Fast + offline (a tiny temp fixture repo for
the core assertions, plus the tiny built-in sunny_garden tasks for real labels).
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.eval import harness, report
from daedalus.eval import tasks as eval_tasks
from daedalus.eval.tasks import TASKS, task_project_label


CORE = '''\
def helper(x):
    """Return x doubled."""
    return x * 2


class Engine:
    def run(self):
        return helper(21)
'''

APP = '''\
from proj import core


def main():
    e = core.Engine()
    return e.run()
'''

UNRELATED = "# unrelated\nSECRET_MARKER = 'nope'\n" + \
    "\n".join(f"def unrelated_{i}():\n    return {i}" for i in range(30))


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class EvalTier1Test(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        _write(self.root, "proj/app.py", APP)
        _write(self.root, "proj/unrelated.py", UNRELATED)
        # Fixture tasks pointing at the temp repo (repo = absolute path).
        self.tasks = [
            {  # focus file + its caller neighborhood -> should fully recall
                "id": "fx_core",
                "repo": str(self.root),
                "target": "proj/core.py",
                "must_include": ["helper", "Engine"],
            },
            {  # deliberately references a symbol NOT in the slice -> a miss
                "id": "fx_miss",
                "repo": str(self.root),
                "target": "proj/core.py",
                "must_include": ["helper", "SECRET_MARKER"],
            },
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_recall_and_compression_ranges(self):
        result = harness.run_tier1(self.tasks)
        self.assertEqual(result["n_tasks"], 2)
        for t in result["per_task"]:
            self.assertGreaterEqual(t["recall"], 0.0)
            self.assertLessEqual(t["recall"], 1.0)
            self.assertGreater(t["compression"], 0.0)
            self.assertLessEqual(t["compression"], 1.0)
            self.assertLess(t["slice_tokens"], t["whole_repo_tokens"])
        # These fixture tasks carry no label_provenance/tier -> default bucket.
        agg = result["by_provenance"]["hand_reachable"]["primary"]
        self.assertGreater(agg["mean_compression"], 0.0)
        self.assertGreaterEqual(agg["mean_recall"], 0.0)
        self.assertLessEqual(agg["mean_recall"], 1.0)

    def test_miss_detection(self):
        result = harness.run_tier1(self.tasks)
        by_id = {t["id"]: t for t in result["per_task"]}
        self.assertEqual(by_id["fx_core"]["recall"], 1.0)
        self.assertEqual(by_id["fx_core"]["missed"], [])
        # unrelated.py (with SECRET_MARKER) is omitted from the slice -> a miss
        self.assertLess(by_id["fx_miss"]["recall"], 1.0)
        self.assertIn("SECRET_MARKER", by_id["fx_miss"]["missed"])
        agg = result["by_provenance"]["hand_reachable"]["primary"]
        self.assertEqual(agg["n_slice_recall_misses"], 1)
        self.assertEqual(agg["missed_ids"], ["fx_miss"])

    def test_report_structure_wellformed(self):
        result = harness.run_tier1(self.tasks)
        for key in ("tier", "n_tasks", "n_primary_tasks", "n_quarantine_tasks",
                    "tokenizer", "per_task", "by_provenance"):
            self.assertIn(key, result)
        # No blended top-level recall/compression -- see daedalus.eval.tasks
        # docstring: "hand_reachable" is circular and must never be the
        # headline number on its own.
        self.assertNotIn("mean_recall", result)
        self.assertNotIn("mean_compression", result)
        text = report.render_tier1(result)
        self.assertIsInstance(text, str)
        self.assertIn("NOT SWE-bench", text)
        self.assertIn("PARTIALLY SELF-GRADED", text)
        # ASCII-safe for a cp1252 Windows console.
        text.encode("ascii")

    def test_tier2_skips_cleanly_without_provider(self):
        # provider="none" forces the no-runtime path -> must skip, never crash.
        result = harness.run_tier2(self.tasks, provider="none")
        self.assertTrue(result.get("skipped"))
        self.assertIn("reason", result)
        text = report.render_tier2(result)
        self.assertIn("SKIPPED", text)
        text.encode("ascii")


class EvalBuiltinTasksTest(unittest.TestCase):
    """Validate the real labels on the tiny sunny_garden bucket (fast)."""

    def test_sunny_garden_fixture_is_part_of_the_installable_eval_package(self):
        root = Path(eval_tasks.SUNNY_GARDEN_FIXTURE).resolve()
        package_root = Path(eval_tasks.__file__).resolve().parent
        self.assertEqual(root.parent, package_root / "fixtures")
        self.assertTrue((root / "garden" / "care.py").is_file())
        self.assertTrue((root / "garden" / "cli.py").is_file())
        self.assertTrue((root / "garden" / "plants.py").is_file())

    def test_sunny_garden_tasks_full_recall(self):
        tasks = [t for t in TASKS if task_project_label(t) == "sunny_garden"]
        self.assertTrue(tasks)
        result = harness.run_tier1(tasks)
        agg = result["by_provenance"]["hand_reachable"]["primary"]
        self.assertEqual(agg["mean_recall"], 1.0)
        self.assertGreater(agg["mean_compression"], 0.0)
        for t in result["per_task"]:
            self.assertEqual(t["missed"], [])
            self.assertEqual(t["label_provenance"], "hand_reachable")
            self.assertEqual(t["label_tier"], "primary")


if __name__ == "__main__":
    unittest.main()
