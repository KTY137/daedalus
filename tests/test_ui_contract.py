"""One-UI-contract (Coffee-retro, Icarus-Jr's napkin): the VS Code webview and
the React webapp must render the SAME dashboard shape, or they will drift into
two products. Both are fed by core.get_dashboard -> this pins that single
source of truth, and that the web API surfaces it unchanged (plus the joined
category shape the Role Wheel needs).
"""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from daedalus import core
from daedalus.interfaces.http import web_api


# The keys BOTH surfaces depend on. If someone adds a key the webview needs,
# it must appear in get_dashboard (the shared contract), not be invented in
# one UI. Kept in sync with tests/test_mission_control.py.
_CONTRACT_KEYS = {
    "ok", "generated_at", "selected_project", "projects", "squads",
    "queue", "metrics", "warnings", "claude_crew", "categories",
    # The promotion verdict. In the contract rather than in one UI precisely so
    # that a surface cannot quietly stop showing whether this system is allowed
    # to promote anything. See tests/test_ui_governance.py.
    "governance",
}


def _offline():
    return mock.patch("urllib.request.urlopen", side_effect=OSError("offline"))


class DashboardContractTests(unittest.TestCase):
    def test_core_dashboard_has_the_shared_contract_keys(self):
        with mock.patch("daedalus.core.list_projects", return_value=[]), \
                mock.patch("daedalus.core._process_rows", return_value=[]), _offline():
            d = core.get_dashboard(None)
        missing = _CONTRACT_KEYS - d.keys()
        self.assertEqual(missing, set(), f"dashboard missing contract keys: {missing}")

    def test_categories_are_joined_for_the_role_wheel(self):
        with mock.patch("daedalus.core.list_projects", return_value=[]), \
                mock.patch("daedalus.core._process_rows", return_value=[]), _offline():
            cats = core.get_dashboard(None)["categories"]
        self.assertIsInstance(cats, list)
        if cats:
            for key in ("id", "name", "icon", "color", "lane", "tier", "agents", "count"):
                self.assertIn(key, cats[0])


class WebApiServesTheSameShapeTests(unittest.TestCase):
    """The webapp's /api/dashboard must be core.get_dashboard verbatim -- no
    second, divergent shaping layer in the API."""

    @classmethod
    def setUpClass(cls):
        cls.port = 8796
        t = threading.Thread(target=web_api.run, args=("127.0.0.1", cls.port), daemon=True)
        t.start()
        # WAIT FOR READINESS, do not sleep at it. A fixed 0.4s was enough on an
        # idle box and not enough under load; the server printed "listening" and
        # the first request timed out anyway.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{cls.port}/api/dashboard", timeout=5).read()
                break
            except urllib.error.HTTPError:
                break                       # answering is enough
            except OSError:
                time.sleep(0.1)

    def _get(self, ep):
        # 8s was a load-dependent flake: this suite failed exactly once tonight,
        # on `TimeoutError: timed out` at socket.py, during a run that shared the
        # box with the acceptance harness and a live model probe. The endpoint
        # was up -- the client gave up. A timeout tuned to an idle machine turns
        # a green suite into a coin flip under load, and a coin-flip test is one
        # people learn to re-run instead of read.
        return json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{ep}", timeout=60).read())

    def test_api_dashboard_matches_core_contract(self):
        api = self._get("/api/dashboard")
        missing = _CONTRACT_KEYS - api.keys()
        self.assertEqual(missing, set(), f"API dashboard missing contract keys: {missing}")

    def test_api_serves_same_role_wheel_data(self):
        # The Role Wheel renders from categories -> the API must serve the SAME
        # taxonomy the webview gets from core, not a divergent copy. Compare the
        # stable identity (ids + lane/tier presets), not live counts/timestamps.
        api = self._get("/api/dashboard")
        direct = core.get_dashboard(None)
        api_cats = {c["id"]: (c["lane"], c["tier"]) for c in api["categories"]}
        core_cats = {c["id"]: (c["lane"], c["tier"]) for c in direct["categories"]}
        self.assertEqual(api_cats, core_cats, "Role Wheel data drift between API and core")

    def test_api_and_core_expose_identical_key_sets(self):
        api = set(self._get("/api/dashboard"))
        direct = set(core.get_dashboard(None))
        # ignore keys that are pure envelope/timing noise
        noise = {"project"}
        self.assertEqual(api - noise, direct - noise, "top-level dashboard keys drifted")


if __name__ == "__main__":
    unittest.main()
