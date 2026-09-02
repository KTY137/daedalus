import json
import tempfile
import unittest
from pathlib import Path

from daedalus.orchestration import categories as cats
from daedalus import core


class CategoriesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_global_seed(self):
        rows = cats.load(None)
        ids = {c["id"] for c in rows}
        self.assertIn("implementation", ids)
        self.assertIn("hardware", ids)
        self.assertGreaterEqual(len(rows), 8)

    def test_validate_fails_closed(self):
        errs = cats.validate({"id": "Bad Id!", "name": "", "icon": "", "color": "blue",
                               "lane": "nope", "tier": "gpt5", "triggers": "notalist"})
        self.assertTrue(any("id" in e for e in errs))
        self.assertTrue(any("color" in e for e in errs))
        self.assertTrue(any("lane" in e for e in errs))
        self.assertTrue(any("tier" in e for e in errs))
        self.assertTrue(any("triggers" in e for e in errs))
        good = cats.normalize({"id": "widgets", "name": "Widgets", "icon": "*",
                                "color": "#112233", "lane": "auto", "tier": "sonnet", "triggers": []})
        self.assertEqual(cats.validate(good), [])

    def test_per_repo_override_precedence(self):
        # Global says 'review' lane is 'local'; a per-repo override recolors
        # and re-lanes it -- the override must win when repo_root is passed,
        # and must not leak into the global (repo_root=None) view.
        cats.update("review", {"color": "#000000", "lane": "claude"}, self.repo)
        merged = cats.get("review", self.repo)
        self.assertEqual(merged["color"], "#000000")
        self.assertEqual(merged["lane"], "claude")
        # name/icon/tier should still be inherited from the global entry
        self.assertEqual(merged["name"], "Review")

        global_only = cats.get("review", None)
        self.assertNotEqual(global_only["color"], "#000000")

        override_path = Path(self.repo) / ".agentenv" / "categories.json"
        self.assertTrue(override_path.exists())
        written = json.loads(override_path.read_text(encoding="utf-8"))
        self.assertEqual(written[0]["id"], "review")

    def test_update_unknown_category_raises(self):
        with self.assertRaises(KeyError):
            cats.update("does-not-exist", {"color": "#ffffff"}, self.repo)

    def test_update_invalid_patch_raises(self):
        with self.assertRaises(ValueError):
            cats.update("review", {"lane": "not-a-lane"}, self.repo)

    def test_preset_for_returns_category_default(self):
        agent = {"name": "hardware-dev", "category": "hardware", "model_tier": "sonnet"}
        preset = cats.preset_for(agent)
        self.assertEqual(preset["lane"], "local_only")
        self.assertEqual(preset["tier"], "opus")

    def test_preset_for_falls_back_when_uncategorized(self):
        preset = cats.preset_for({"name": "mystery-dev", "model_tier": "haiku"})
        self.assertEqual(preset, {"lane": "auto", "tier": "haiku"})

    def test_get_categories_joins_agents(self):
        envelope = core.get_categories(None)
        self.assertTrue(envelope["ok"])
        rows = envelope["categories"]
        hardware = next(c for c in rows if c["id"] == "hardware")
        self.assertIn("hardware-dev", [a["name"] for a in hardware["agents"]])
        self.assertEqual(hardware["count"], len(hardware["agents"]))
        review = next(c for c in rows if c["id"] == "review")
        review_agent_names = {a["name"] for a in review["agents"]}
        self.assertIn("qa-critic", review_agent_names)


if __name__ == "__main__":
    unittest.main()
