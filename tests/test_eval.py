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
        self.assertGreater(result["mean_compression"], 0.0)
        self.assertGreaterEqual(result["mean_recall"], 0.0)
        self.assertLessEqual(result["mean_recall"], 1.0)

    def test_miss_detection(self):
        result = harness.run_tier1(self.tasks)
        by_id = {t["id"]: t for t in result["per_task"]}
        self.assertEqual(by_id["fx_core"]["recall"], 1.0)
        self.assertEqual(by_id["fx_core"]["missed"], [])
        # unrelated.py (with SECRET_MARKER) is omitted from the slice -> a miss
        self.assertLess(by_id["fx_miss"]["recall"], 1.0)
        self.assertIn("SECRET_MARKER", by_id["fx_miss"]["missed"])
        self.assertEqual(result["n_slice_recall_misses"], 1)

    def test_report_structure_wellformed(self):
        result = harness.run_tier1(self.tasks)
        for key in ("tier", "n_tasks", "mean_recall", "mean_compression",
                    "n_slice_recall_misses", "tokenizer", "per_task"):
            self.assertIn(key, result)
        text = report.render_tier1(result)
        self.assertIsInstance(text, str)
        self.assertIn("NOT SWE-bench", text)
        self.assertIn("mean recall", text)
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

    def test_sunny_garden_tasks_full_recall(self):
        tasks = [t for t in TASKS if task_project_label(t) == "sunny_garden"]
        self.assertTrue(tasks)
        result = harness.run_tier1(tasks)
        self.assertEqual(result["mean_recall"], 1.0)
        self.assertGreater(result["mean_compression"], 0.0)
        for t in result["per_task"]:
            self.assertEqual(t["missed"], [])


if __name__ == "__main__":
    unittest.main()
