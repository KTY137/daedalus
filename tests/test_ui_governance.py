"""The promotion verdict must reach every surface, and must never read green.

Three mechanisms landed in this repo -- the discrimination gate, the installed
self-policy's write confinement, and the operability drill -- and until now an
operator could not answer "may this system promote anything right now, and why
not" from ANY surface. `core.get_governance` is that answer.

These tests exist because the answer is only useful if it cannot rot:

* it must AGREE with `spine.bootstrap`, which is the real authority on
  promotion, rather than forming a cheerful second opinion;
* it must degrade to the WORST gate, never to an average;
* it must say "unknown" when it does not know, never a plausible zero;
* and BOTH UI surfaces must actually render it, or a capability goes invisible
  again exactly the way this whole surface was built to stop.

The last of those is a source-level check on the two UIs. That is deliberately
a weaker claim than "the pixel is on the screen" and is labelled as such in
each test: it proves the field is WIRED, not that a human can read it. It still
fails loudly the moment a surface drops the field, which is the drift this file
is here to catch.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from daedalus import core
from daedalus.interfaces.http import web_api

REPO = Path(__file__).resolve().parents[1]
EXTENSION_JS = REPO / "vscode-agent-env" / "extension.js"
WEBAPP_SRC = REPO / "apps" / "web" / "src"

_VALID_STATES = set(core.GOVERNANCE_STATES)
_VALID_PROVENANCE = {"MEASURED", "INHERITED", "ASSUMED"}


def _offline():
    return mock.patch("urllib.request.urlopen", side_effect=OSError("offline"))


class GovernanceShapeTests(unittest.TestCase):
    def test_payload_has_the_operator_question_answered(self):
        g = core.get_governance(None)
        for key in ("promotion_allowed", "verdict", "state", "gates",
                    "blockers", "head", "states_vocabulary"):
            self.assertIn(key, g, f"governance payload missing {key!r}")
        self.assertIsInstance(g["promotion_allowed"], bool)
        self.assertIn(g["state"], _VALID_STATES)
        self.assertTrue(g["verdict"].strip(), "the verdict must be words, not empty")

    def test_every_gate_carries_a_state_and_a_provenance(self):
        """A number with no provenance is a rumour."""
        g = core.get_governance(None)
        self.assertTrue(g["gates"], "there must be at least one gate")
        for gate in g["gates"]:
            for key in ("id", "question", "state", "headline", "provenance"):
                self.assertIn(key, gate, f"gate {gate.get('id')!r} missing {key!r}")
            self.assertIn(gate["state"], _VALID_STATES,
                          f"gate {gate['id']!r} invented state {gate['state']!r}")
            self.assertIn(gate["provenance"], _VALID_PROVENANCE,
                          f"gate {gate['id']!r} has unlabelled provenance")
            self.assertTrue(gate["headline"].strip(),
                            f"gate {gate['id']!r} has no human-readable reason")

    def test_the_three_capabilities_are_all_represented(self):
        """The specific work that was invisible. If a gate id disappears, the
        capability has silently left the product surface again."""
        ids = {g["id"] for g in core.get_governance(None)["gates"]}
        self.assertEqual(
            ids, {"discrimination", "write_confinement", "operability_drill"},
            "a governance gate was added or dropped without updating the surface")

    def test_refusal_always_explains_why(self):
        g = core.get_governance(None)
        if not g["promotion_allowed"]:
            self.assertTrue(g["blockers"], "promotion refused with no blocker named")
            for b in g["blockers"]:
                self.assertTrue(b["why"].strip(),
                                f"blocker {b['gate']!r} refuses without saying why")


class NeverGreenByAccidentTests(unittest.TestCase):
    """The five states must not collapse into green."""

    def test_worst_gate_wins_never_the_average(self):
        self.assertEqual(core._worst_state(["working", "working", "absent"]), "absent")
        self.assertEqual(core._worst_state(["working", "degraded"]), "degraded")
        self.assertEqual(core._worst_state(["working", "working"]), "working")
        self.assertEqual(core._worst_state(["absent", "unknown"]), "unknown")

    def test_no_gates_is_unknown_not_working(self):
        self.assertEqual(core._worst_state([]), "unknown")

    def test_missing_discrimination_receipt_is_absent_not_passing(self):
        """A gate nobody measured is not a gate that passed."""
        gate = core._gov_discrimination(str(REPO / "no_such_repo_dir"), "deadbeef")
        self.assertNotEqual(gate["state"], "working")
        self.assertIn(gate["state"], _VALID_STATES)

    def test_unreadable_revision_refuses_rather_than_permits(self):
        """`head=None` must never be read as 'nothing to compare, so fine'."""
        gate = core._gov_discrimination(str(REPO), None)
        self.assertNotEqual(gate["state"], "working",
                            "an unreadable revision was treated as proof")

    def test_a_raising_governance_check_reads_unknown_not_ok(self):
        with mock.patch("daedalus.core.get_governance",
                        side_effect=RuntimeError("boom")), \
                mock.patch("daedalus.core.list_projects", return_value=[]), \
                mock.patch("daedalus.core._process_rows", return_value=[]), _offline():
            d = core.get_dashboard(None)
        gov = d["governance"]
        self.assertFalse(gov["promotion_allowed"],
                         "a failed governance check granted promotion")
        self.assertEqual(gov["state"], "unknown")
        self.assertIn("UNKNOWN", gov["verdict"])

    def test_policyless_project_reports_unconfined_not_confined(self):
        gate = core._gov_write_confinement("", None)
        self.assertNotEqual(gate["state"], "working")

    def test_incomplete_drill_is_not_a_pass(self):
        """'skipped' is never 'pass' -- an unexercised control is INCOMPLETE."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "runs" / "spine").mkdir(parents=True)
            (root / "runs" / "spine" / "operability_drill.json").write_text(
                json.dumps({"head": "abc123abc123", "passed": 5, "failed": 0,
                            "incomplete": 2, "scheduling_defensible": False}),
                encoding="utf-8")
            gate = core._gov_operability_drill(str(root), "abc123abc123")
        self.assertNotEqual(gate["state"], "working")
        self.assertIn("INCOMPLETE", gate["headline"])


class AgreesWithTheRealAuthorityTests(unittest.TestCase):
    """This surface must not become a second opinion on promotion."""

    def test_promotion_allowed_matches_gate_discrimination_exactly(self):
        from daedalus.spine.bootstrap import gate_discrimination

        g = core.get_governance(None)
        repo_root = g["repo_root"] or str(REPO)
        truth = gate_discrimination(repo_root, head=g["head"])
        self.assertEqual(
            g["promotion_allowed"], truth.proven,
            "the governance surface disagrees with spine.bootstrap about "
            "whether promotion is allowed -- the surface must never be the "
            "more permissive of the two")

    def test_surface_never_permits_what_the_shadow_runner_refuses(self):
        """The one-directional guarantee, stated separately from equality so it
        survives any future loosening of the test above."""
        from daedalus.spine.bootstrap import gate_discrimination

        g = core.get_governance(None)
        truth = gate_discrimination(g["repo_root"] or str(REPO), head=g["head"])
        if g["promotion_allowed"]:
            self.assertTrue(truth.proven, "surface permitted an unproven gate")

    def test_discrimination_gate_reason_is_carried_verbatim(self):
        """The operator must see the REAL reason, not a paraphrase."""
        from daedalus.spine.bootstrap import gate_discrimination

        g = core.get_governance(None)
        disc = next(x for x in g["gates"] if x["id"] == "discrimination")
        truth = gate_discrimination(g["repo_root"] or str(REPO), head=g["head"])
        if disc.get("reason"):
            self.assertEqual(disc["reason"], truth.reason)


class WriteConfinementIsMeasuredNotReadTests(unittest.TestCase):
    """Reading `write_allow` out of a config proves somebody typed it. This
    repo already learned that the expensive way: a prose policy claimed to deny
    12 paths and 8 were writable. So the gate must probe the live predicate."""

    def test_confinement_gate_probes_the_real_write_predicate(self):
        """Resolved through `config.resolve_project` with the real project
        name, exactly as offload's live write path does -- not from a config
        dict handed in by the test, which could be one the write path would
        never have chosen."""
        gate = core._gov_write_confinement(str(REPO), "agent_env")
        self.assertEqual(gate["state"], "working")
        self.assertEqual(gate["provenance"], "MEASURED")
        detail = gate["detail"]
        self.assertTrue(detail["probe_outside_allow_blocked"],
                        "a path outside write_allow was writable")
        self.assertFalse(detail["probe_inside_allow_blocked"],
                         "a path inside write_allow was blocked")

    def test_no_policy_at_all_is_reported_as_unconfined(self):
        """No policy ANYWHERE is an unconfined write lane, and must be named as
        such rather than shown as 'a policy is installed' (true, and completely
        misleading)."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            gate = core._gov_write_confinement(td, None)
        self.assertEqual(gate["state"], "absent")
        self.assertIn("UNCONFINED", gate["headline"])

    def test_a_policy_declaring_no_write_allow_is_unconfined(self):
        """A policy with only an egress `allow` list confines nothing: the
        egress axis does not gate writes. That must read as absent, not as
        'a policy is installed'."""
        import json as _json
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            cfgdir = Path(td) / ".agentenv"
            cfgdir.mkdir()
            (cfgdir / "agentenv.json").write_text(
                _json.dumps({"name": "t", "repo_root": td,
                             "policy": {"allow": ["docs/"], "default_deny": True}}),
                encoding="utf-8")
            gate = core._gov_write_confinement(td, None)
        self.assertEqual(gate["state"], "absent")
        self.assertIn("UNCONFINED", gate["headline"])

    def test_naming_a_project_must_not_widen_the_write_lane(self):
        """THE INVARIANT, kept after the specific bypass was closed.

        History, because it explains the shape of this test. The registry entry
        `projects/<name>.json` used to shadow the repo-local
        `.agentenv/agentenv.json`, so `--project agent_env` ran with NO
        write_allow while the unnamed case was confined. Commit 8e48783 closed
        that by intersecting the repo-local confinement into the named entry.

        The earlier version of this test asserted the bypass was present -- and
        it was WORTHLESS, because it fed a synthetic dict straight to the render
        function instead of going through `resolve_project`. It passed before
        the fix and it passed after the fix. A test that cannot tell the
        difference is not a gate.

        So this asserts the durable property instead of the historical bug, and
        it asserts it through the resolver: naming a project must never grant
        MORE write permission than not naming one.
        """
        from daedalus.config import resolve_project
        from daedalus.sensitivity import load_policy

        unnamed = set(load_policy(resolve_project(str(REPO), None)).write_allow)
        named = set(load_policy(resolve_project(str(REPO), "agent_env")).write_allow)
        self.assertTrue(unnamed, "the repo-local policy declares no write_allow")
        self.assertFalse(
            named - unnamed,
            f"naming the project WIDENS the write lane by {sorted(named - unnamed)} "
            f"-- naming a project must never grant more permission than not "
            f"naming one")

    def test_surface_reports_a_widened_write_lane_as_degraded(self):
        """And if that invariant is ever broken, the SURFACE must say so rather
        than render a reassuring allow-list. Exercised with a stubbed resolver
        because the real tree (correctly) no longer produces this state."""
        narrow = {"repo_root": str(REPO), "policy": {"write_allow": ["docs/"]}}
        wide = {"repo_root": str(REPO), "policy": {"write_allow": ["docs/", "daedalus/"]}}

        def fake_resolve(root, proj):
            return wide if proj else narrow

        with mock.patch("daedalus.config.resolve_project", side_effect=fake_resolve):
            gate = core._gov_write_confinement(str(REPO), "agent_env")
        self.assertEqual(gate["state"], "degraded",
                         "a widened write lane rendered as confined")
        self.assertIn("widens", gate["headline"].lower())
        self.assertIn("daedalus/", gate["detail"]["widened_by_naming"])

    def test_the_repo_local_confinement_really_does_declare_write_allow(self):
        """Anchors the tests above to reality: if .agentenv/agentenv.json stops
        declaring write_allow, the invariant test is comparing empty sets and
        would pass vacuously."""
        from daedalus.config import resolve_project

        local = resolve_project(str(REPO), None) or {}
        self.assertTrue((local.get("policy") or {}).get("write_allow"),
                        ".agentenv/agentenv.json no longer declares write_allow")

    def test_confinement_that_does_not_hold_is_degraded_not_working(self):
        """A declared allow-list that the live predicate does not actually
        enforce is the original sin this gate exists to catch: a document
        describing a fence the code does not have."""
        with mock.patch("daedalus.sensitivity.path_write_blocked", return_value=False):
            gate = core._gov_write_confinement(str(REPO), "agent_env")
        self.assertEqual(gate["state"], "degraded")
        self.assertIn("does not hold", gate["headline"])


class BothSurfacesRenderItTests(unittest.TestCase):
    """A capability reachable from the API but invisible in both UIs is exactly
    the gap this whole file exists to close.

    SCOPE, stated honestly: these assert the field is WIRED INTO THE SOURCE of
    each surface. They do not prove a human can read it on screen. They do fail
    the moment a surface stops referencing the verdict, which is the drift that
    made this work necessary.
    """

    def test_vscode_surface_reaches_governance_through_the_web_app(self):
        """The VS Code surface is a WINDOW, not a second renderer.

        MEASURED: both webview entry points assign `agentOsHtml`, which iframes
        the React app. So the honest claim for VS Code is that it iframes the
        web app, and the web app renders the verdict -- NOT that extension.js
        draws it. An earlier version of this test asserted only that the string
        "governance" appeared somewhere in extension.js. That passed while the
        only occurrence was inside a template with zero callers: a green test
        for a capability no user could reach, which is the exact defect class
        this whole file was written to catch.
        """
        src = EXTENSION_JS.read_text(encoding="utf-8", errors="replace")
        self.assertIn("agentOsHtml", src)
        self.assertRegex(
            src, r"webview\.html\s*=\s*agentOsHtml",
            "the VS Code webview no longer renders the web app, so whatever it "
            "renders now must be re-checked for the promotion verdict")
        self.assertIn("iframe", src,
                      "agentOsHtml no longer embeds the web app")
        # ...and the thing it embeds must itself render the verdict.
        self.test_web_app_renders_the_promotion_verdict()

    def test_dead_mission_control_template_is_not_an_extension_surface(self):
        """The legacy HTML dashboard is retired; only the React cockpit ships."""
        src = EXTENSION_JS.read_text(encoding="utf-8", errors="replace")
        self.assertNotRegex(src, r"function\s+dashboardHtml\s*\(")
        self.assertIn("function agentOsHtml", src)
        self.assertIn("<iframe", src)

    def test_web_app_renders_the_promotion_verdict(self):
        hits = [p for p in WEBAPP_SRC.rglob("*.ts*")
                if "governance" in p.read_text(encoding="utf-8", errors="replace")]
        self.assertTrue(hits,
                        "no file under apps/web/src references governance -- the "
                        "promotion verdict is invisible in the web app")
        joined = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in hits)
        self.assertIn("promotion_allowed", joined,
                      "the web app does not render whether promotion is allowed")

    def test_both_surfaces_name_the_same_gates(self):
        """If one UI hard-codes a gate list, it drifts the moment core changes.
        Neither may enumerate gate ids that core does not produce."""
        ids = {g["id"] for g in core.get_governance(None)["gates"]}
        ext = EXTENSION_JS.read_text(encoding="utf-8", errors="replace")
        web = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                        for p in WEBAPP_SRC.rglob("*.ts*"))
        for surface_name, src in (("extension.js", ext), ("apps/web", web)):
            for quoted in re.findall(r"['\"](discrimination|write_confinement|"
                                     r"operability_drill)['\"]", src):
                self.assertIn(quoted, ids,
                              f"{surface_name} names gate {quoted!r} which core "
                              f"no longer produces")

    def test_webview_render_blocks_contain_no_backtick(self):
        """MEASURED trap, hit TWICE while writing this: the Mission Control
        webview's script lives inside a JS template literal, so a single
        backtick in a comment truncates the ENTIRE webview at that point.
        `node --check` on extension.js does not catch it -- to the outer parser
        the block is just a string -- so the panel silently renders blank
        instead of failing loudly. Cheap to pin, and it already earned its keep.
        """
        src = EXTENSION_JS.read_text(encoding="utf-8", errors="replace")
        for start_marker, end_marker in (
                ("const GOV_STATE_META", "function renderQuality()"),
                ("function renderQuality()", "const WHEEL_COLOR_CHOICES")):
            start, end = src.find(start_marker), src.find(end_marker)
            self.assertNotEqual(start, -1, f"{start_marker} vanished")
            self.assertGreater(end, start, f"{end_marker} moved above {start_marker}")
            block = src[start:end]
            self.assertNotIn("`", block,
                             f"a backtick in the {start_marker!r} block will "
                             f"truncate the whole Mission Control webview")
            self.assertNotIn("${", block,
                             f"a ${{...}} interpolation in the {start_marker!r} "
                             f"block is evaluated at extension load time, not "
                             f"in the webview")

    def test_quality_gates_do_not_render_unmeasured_as_pass(self):
        """MEASURED defect, fixed: the Quality Gates tab negated
        q.stale_watchers and q.fallback_alarm directly, so a MISSING quality
        block (failed fetch, older backend) made both negations true and the
        panel showed two green PASSES for measurements never taken. An absent
        input must render `unknown`, and `unknown` is not a pass.
        """
        src = EXTENSION_JS.read_text(encoding="utf-8", errors="replace")
        start, end = src.find("function renderQuality()"), src.find("const WHEEL_COLOR_CHOICES")
        block = src[start:end]
        for banned in ("pass: !q.stale_watchers", "pass: !q.fallback_alarm"):
            self.assertNotIn(banned, block,
                             f"{banned!r} renders an unmeasured gate as passing")
        self.assertIn("unknown", block,
                      "the Quality Gates tab has no 'unknown' rendering, so an "
                      "unmeasured gate must be collapsing into pass or fail")
        # The rate meter must not invent the most flattering number available.
        self.assertNotIn("Math.round((q.fallback_rate || 0) * 100) + '%'", block,
                         "an unmeasured fallback rate is being rendered as 0%")

    def test_neither_surface_hardcodes_a_green_promotion_verdict(self):
        """Guard against the failure mode this repo hit ten times this week:
        a surface that renders a reassuring literal instead of a measurement."""
        ext = EXTENSION_JS.read_text(encoding="utf-8", errors="replace")
        for bad in ("promotion_allowed: true", "promotion_allowed = true",
                    'promotionAllowed = true', "promotion_allowed: !0"):
            self.assertNotIn(bad, ext,
                             f"extension.js hard-codes a passing promotion verdict: {bad!r}")


class ApiServesTheSameVerdictTests(unittest.TestCase):
    """/api/governance and dashboard['governance'] must be one answer."""

    @classmethod
    def setUpClass(cls):
        cls.port = 8797
        t = threading.Thread(target=web_api.run, args=("127.0.0.1", cls.port),
                             daemon=True)
        t.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{cls.port}/api/governance", timeout=5).read()
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.1)

    def _get(self, ep):
        return json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{ep}", timeout=60).read())

    @staticmethod
    def _stable(payload: dict) -> dict:
        return {k: v for k, v in payload.items()
                if k not in ("generated_at", "project")}

    def test_endpoint_exists_and_answers_the_question(self):
        api = self._get("/api/governance")
        self.assertIn("promotion_allowed", api)
        self.assertIn("verdict", api)

    def test_endpoint_matches_the_dashboard_block_verbatim(self):
        api = self._get("/api/governance")
        embedded = self._get("/api/dashboard")["governance"]
        self.assertEqual(
            self._stable(api), self._stable(embedded),
            "the standalone governance endpoint and the dashboard's embedded "
            "copy disagree -- two surfaces, two answers")

    def test_endpoint_matches_core_verbatim(self):
        api = self._get("/api/governance")
        direct = core.get_governance(None)
        self.assertEqual(self._stable(api), self._stable(direct),
                         "the API reshapes the governance verdict")


if __name__ == "__main__":
    unittest.main()
