"""GET /api/catalogue -- the GUI parts index, served read-only.

``daedalus/gui_catalogue.py`` was reachable from nothing but its own test. This
pins the one route that reads it, and pins the property that made the route
safe to add in the first place: it is a PURE READ.

Why the purity assertion is not decoration: ``do_POST`` and ``do_PUT`` call
``effect_boundary.begin_effect`` with a registry row. ``do_GET`` has no row --
there is no ``daedalus.web_api:DaedalusHandler.do_GET`` entry in
``daedalus/spine/effect_boundary.py``. So every GET route must stay inside "no
declared effect", and a route that opened the latent vector store, wrote a
cache, or reached the network would be an UNDECLARED effect on an undeclared
surface. ``CatalogueRouteIsPureReadTest`` is what notices.
"""
from __future__ import annotations

import ast
import inspect
import sys
import unittest


def _get(path: str) -> dict:
    """Drive one GET through the real dispatcher, in process.

    Same shape as ``tests/test_web_api.py::LatentSearchRouteTest._get``: an
    unmatched path falls through to ``_send_static``, so "static not called"
    is the proof that the route literal actually matched.
    """
    from daedalus.web_api import DaedalusHandler

    handler = object.__new__(DaedalusHandler)
    handler.path = path
    captured: dict = {}

    def send_json(payload, status: int = 200) -> None:
        captured["payload"] = payload
        captured["status"] = status

    handler._send_json = send_json
    handler._send_static = lambda p: captured.setdefault("static", p)
    handler._handle_get()
    return captured


class CatalogueRouteTest(unittest.TestCase):
    def test_route_dispatches_and_returns_the_catalogue(self) -> None:
        captured = _get("/api/catalogue")
        self.assertNotIn("static", captured, "route literal did not match")
        self.assertEqual(captured["status"], 200)
        payload = captured["payload"]
        self.assertTrue(payload["ok"])
        catalogue = payload["catalogue"]
        self.assertEqual(catalogue["schema"], "daedalus-gui-catalogue/1")
        # The seeded files are tracked in git (catalogue/gui/*.json), so this
        # is a fact about the repo, not about a machine.
        self.assertIn("glass.json", catalogue["sources"])
        self.assertIn("external.json", catalogue["sources"])
        self.assertGreater(catalogue["entry_count"], 0)
        self.assertEqual(len(catalogue["entries"]), catalogue["entry_count"])

    def test_every_entry_carries_its_licence_and_derived_use_mode(self) -> None:
        """The reason this module exists: no part is shown without the terms
        on which it may be used. React Bits ships 'MIT + Commons Clause' --
        a reader who saw the component and not the licence would copy source
        its licence forbids redistributing."""
        catalogue = _get("/api/catalogue")["payload"]["catalogue"]
        for entry in catalogue["entries"]:
            self.assertTrue(entry.get("licence"), f"{entry['name']} has no licence")
            self.assertIn(
                entry.get("use_mode"),
                ("copy_in", "reciprocal", "reference_only"),
                f"{entry['name']} has no derived use_mode",
            )

    def test_refusals_are_reported_not_hidden(self) -> None:
        catalogue = _get("/api/catalogue")["payload"]["catalogue"]
        self.assertIn("rejected", catalogue)
        self.assertEqual(len(catalogue["rejected"]), catalogue["rejected_count"])

    def test_q_ranks_entries_and_reports_that_latent_was_not_used(self) -> None:
        captured = _get("/api/catalogue?q=animated%20glass%20card&limit=3")
        self.assertEqual(captured["status"], 200)
        search = captured["payload"]["search"]
        self.assertEqual(search["objective"], "animated glass card")
        self.assertLessEqual(len(search["hits"]), 3)
        self.assertTrue(search["hits"], "BM25 returned nothing for a seeded term")
        # Ranking is real, not insertion order: a glass query puts a glass
        # entry on top, and every hit name resolves against the entries the
        # same response carried.
        self.assertTrue(search["hits"][0]["name"].startswith("glass/"))
        names = {e["name"] for e in captured["payload"]["catalogue"]["entries"]}
        for hit in search["hits"]:
            self.assertIn(hit["name"], names)
        self.assertFalse(search["seeds"]["latent_applied"])

    def test_no_q_means_no_search_block(self) -> None:
        self.assertNotIn("search", _get("/api/catalogue")["payload"])

    def test_limit_and_q_are_validated(self) -> None:
        for path, expected in (
            ("/api/catalogue?q=x&limit=abc", "limit must be an integer"),
            ("/api/catalogue?q=x&limit=0", "limit must be between 1 and 100"),
            ("/api/catalogue?q=x&limit=101", "limit must be between 1 and 100"),
            ("/api/catalogue?q=" + "a" * 2001, "q must be at most 2000 characters"),
        ):
            with self.subTest(path=path[:40]):
                captured = _get(path)
                self.assertEqual(captured["status"], 400)
                self.assertEqual(captured["payload"]["error"], expected)
                self.assertFalse(captured["payload"]["ok"])


class CatalogueRouteIsPureReadTest(unittest.TestCase):
    """The route performs no write, no spawn and no socket work.

    A refusal test with no control proves nothing (docs/HANDOFF.md), so
    :meth:`test_control_the_audit_hook_actually_fires` deliberately writes,
    connects and spawns under the same hook. If that control ever goes green
    with zero detections, the purity assertion below is vacuous and this test
    is lying.
    """

    _WRITE_MODES = frozenset("wax+")
    _FORBIDDEN = (
        "subprocess.", "socket.", "os.system", "os.spawn", "os.exec",
        "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod",
        "os.truncate", "shutil.", "urllib.", "ftplib.", "http.client.",
        "tempfile.mkstemp", "tempfile.mkdtemp",
    )

    # An audit hook can never be uninstalled, so exactly one is installed for
    # the process and gated by a flag. It must not raise: an exception inside
    # an audit hook becomes a RuntimeError at an arbitrary call site.
    _violations: list = []
    _active = [False]
    _installed = [False]

    @classmethod
    def setUpClass(cls) -> None:
        if cls._installed[0]:
            return

        violations, active, write_modes, forbidden = (
            cls._violations, cls._active, cls._WRITE_MODES, cls._FORBIDDEN,
        )

        def hook(event: str, args: tuple) -> None:
            if not active[0]:
                return
            if event == "open":
                mode = args[1] if len(args) > 1 else None
                if isinstance(mode, str) and (set(mode) & write_modes):
                    violations.append(f"open-for-write {str(args[0])[:120]}")
                return
            for prefix in forbidden:
                if event.startswith(prefix):
                    violations.append(f"{event} {str(args)[:120]}")
                    return

        sys.addaudithook(hook)
        cls._installed[0] = True

    def _record(self, body) -> list:
        self._violations.clear()
        self._active[0] = True
        try:
            body()
        finally:
            self._active[0] = False
        return list(self._violations)

    def test_serving_the_catalogue_writes_spawns_and_connects_nothing(self) -> None:
        # WARM UP FIRST, un-audited. The route imports gui_catalogue lazily,
        # and CPython writes __pycache__/*.pyc on a module's first import --
        # a genuine open-for-write that belongs to the interpreter, not to the
        # endpoint. Auditing the first-ever call would fail on a cold tree and
        # pass on a warm one, which is a test that reports the state of a
        # cache instead of the property under test.
        _get("/api/catalogue?q=glass%20card&limit=5")

        captured: dict = {}
        found = self._record(
            lambda: captured.update(_get("/api/catalogue?q=glass%20card&limit=5"))
        )
        self.assertEqual(captured["status"], 200, "the call under audit must succeed")
        self.assertEqual(
            found, [],
            "GET /api/catalogue is declared a pure read but performed: "
            + "; ".join(found),
        )

    def test_control_the_audit_hook_actually_fires(self) -> None:
        import os
        import socket
        import subprocess
        import tempfile

        target = os.path.join(tempfile.gettempdir(), "daedalus-catalogue-audit-control")

        def body() -> None:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("control")
            sock = socket.socket()
            try:
                sock.connect(("127.0.0.1", 9))
            except OSError:
                pass
            finally:
                sock.close()
            subprocess.run([sys.executable, "-c", "pass"], capture_output=True)

        try:
            found = self._record(body)
        finally:
            if os.path.exists(target):
                os.remove(target)

        kinds = {row.split()[0] for row in found}
        self.assertTrue(
            any(k == "open-for-write" for k in kinds), f"write undetected: {found}")
        self.assertTrue(
            any(k.startswith("socket.") for k in kinds), f"socket undetected: {found}")
        self.assertTrue(
            any(k.startswith("subprocess.") for k in kinds), f"spawn undetected: {found}")


class CatalogueRouteStaysOffTheLatentPathTest(unittest.TestCase):
    def test_search_is_called_with_use_latent_false(self) -> None:
        """Assert on the AST, not on the prose (docs/HANDOFF.md).

        The latent half of gui_catalogue.search opens an EventVectorStore --
        a real effect. do_GET declares none, so this route must pass
        use_latent=False explicitly. A future edit that flips it, or that
        drops the keyword and inherits a changed default, fails here."""
        from daedalus import web_api

        tree = ast.parse(inspect.getsource(web_api))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "search"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "gui_catalogue"
        ]
        self.assertEqual(len(calls), 1, "expected exactly one gui_catalogue.search call")
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertIn("use_latent", keywords, "use_latent must be passed explicitly")
        self.assertIsInstance(keywords["use_latent"], ast.Constant)
        self.assertIs(keywords["use_latent"].value, False)

    def test_do_get_still_has_no_effect_boundary_row(self) -> None:
        """The premise of the purity requirement. If someone later gives
        do_GET a registry row and a begin_effect call, this test fails and
        the reasoning in this file must be revisited rather than assumed."""
        from daedalus.spine import effect_boundary

        source = inspect.getsource(effect_boundary)
        self.assertNotIn("do_GET", source)


if __name__ == "__main__":
    unittest.main()
