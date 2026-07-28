import tempfile
import unittest

from daedalus import agents_registry as reg
from daedalus import router, core
from daedalus.kairos.scheduler import KairosScheduler


class AgentsRegistryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _spec(self, name="security-reviewer", **kw):
        base = dict(name=name, call_name="Argus", model_tier="opus", external_ok=False,
                    owns=["auth/"], triggers=["auth", "crypto"], output_schema="review_report_v1")
        base.update(kw)
        return base

    def test_create_load_route_round_trip(self):
        reg.create_role(self._spec(), self.repo)
        self.assertIn("security-reviewer", [r["name"] for r in reg.list_roles(self.repo)])
        picked = router.route_task("please review the auth flow", [], repo_root=self.repo)
        self.assertEqual(picked["name"], "security-reviewer")

    def test_validation_fails_closed(self):
        with self.assertRaises(ValueError):
            reg.create_role({"name": "Bad Name", "model_tier": "gpt"}, self.repo)
        errs = reg.validate_role({"name": "ok-name", "model_tier": "haiku", "owns": "notalist"})
        self.assertTrue(any("owns" in e for e in errs))

    def test_duplicate_refused_then_overwrite(self):
        reg.create_role(self._spec(), self.repo)
        with self.assertRaises(FileExistsError):
            reg.create_role(self._spec(), self.repo)
        reg.create_role(self._spec(model_tier="sonnet"), self.repo, overwrite=True)
        self.assertEqual(reg.get_role("security-reviewer", self.repo)["model_tier"], "sonnet")

    def test_reserved_name_categories_rejected(self):
        # A role named 'categories' collides with the taxonomy file and would
        # vanish from load_agents -- reject it at creation, not silently.
        with self.assertRaises(ValueError):
            reg.create_role({"name": "categories", "model_tier": "sonnet"}, self.repo)
        self.assertTrue(any("reserved" in e for e in reg.validate_role({"name": "categories"})))

    def test_update_and_delete(self):
        reg.create_role(self._spec(), self.repo)
        reg.update_role("security-reviewer", {"model_tier": "sonnet", "triggers": ["auth"]}, self.repo)
        role = reg.get_role("security-reviewer", self.repo)
        self.assertEqual(role["model_tier"], "sonnet")
        self.assertEqual(role["triggers"], ["auth"])
        self.assertTrue(reg.delete_role("security-reviewer", self.repo))
        self.assertIsNone(reg.get_role("security-reviewer", self.repo))

    def test_update_unknown_raises(self):
        with self.assertRaises(KeyError):
            reg.update_role("nope", {"model_tier": "sonnet"}, self.repo)

    def test_normalize_fills_defaults(self):
        role = reg.normalize_role({"name": "minimal"})
        self.assertEqual(role["model_tier"], "sonnet")
        self.assertEqual(role["owns"], [])
        self.assertFalse(role["external_ok"])

    def test_ikarus_configure_creates_then_updates(self):
        ik = KairosScheduler()
        self.assertEqual(ik.configure(self._spec(), self.repo)["action"], "created")
        r2 = ik.configure({"name": "security-reviewer", "model_tier": "haiku"}, self.repo)
        self.assertEqual(r2["action"], "updated")
        self.assertEqual(reg.get_role("security-reviewer", self.repo)["model_tier"], "haiku")

    def test_bridge_configure_strategy_is_local_never_claude(self):
        payload = {"strategy": "configure", "repo_root": self.repo,
                   "role": self._spec(name="doc-bot", model_tier="haiku", output_schema="agent_report_v1")}
        report = core.process_bridge_payload(payload)
        self.assertEqual(report["bridge_status"], "done")
        self.assertNotEqual(report.get("lane"), "claude")
        self.assertEqual(report["result"]["action"], "created")
        self.assertIsNotNone(reg.get_role("doc-bot", self.repo))

    def test_bridge_configure_invalid_fails_not_claude(self):
        report = core.process_bridge_payload(
            {"strategy": "configure", "repo_root": self.repo, "role": {"name": "Bad Name"}})
        self.assertEqual(report["bridge_status"], "failed")
        self.assertNotEqual(report.get("lane"), "claude")


if __name__ == "__main__":
    unittest.main()
