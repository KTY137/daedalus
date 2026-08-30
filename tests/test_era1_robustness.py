# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Era-1 robustness fixes, each pinned by a regression test:

1. ``offload`` result carries ``wrote`` -- the GROUND-TRUTH list of files that
   really changed on disk. Advisory drafts report []; a rolled-back escalation
   reports [] (unless dirty). Callers must render write claims from this field
   (the op-test harness once printed 'wrote yes' for pure advisory drafts).
2. ``route_and_select``/``offload`` thread ``repo_root`` so a repo whose crew
   lives only in its own ``.agentenv/agents/`` can route (used to RuntimeError
   with 'no active agents configured').
3. ``_run_rewrite`` supports greenfield CREATE (path that doesn't exist yet).
4. Verifier gates .js (node --check) and .html (truncation tripwire).
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.provider_router import route_and_select
from daedalus.verifier import verify
# THE LIVE CASCADE TAKES A LEASE NOW, AND SO DOES THIS TEST. The shim that
# used to stand here called ``daedalus.offload._offload_impl`` directly with
# ``live=True`` -- a complete, un-leased write path. That second caller is
# exactly why ``scripts/declare_write_surfaces.py`` could not attribute the
# provider run to ``python.offload``'s Effect Lease: a write reachable from a
# leased AND an un-leased caller is attributable to neither. The planner no
# longer executes anything, so these tests take the door production takes.
from test_offload_lease_harness import live_offload as offload


_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False}


def _report(files_changed=None, status="done"):
    return {"status": status, "summary": "s", "files_changed": files_changed or [],
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


def _make_repo(tmp: str, *, agents: list[dict] | None = None) -> str:
    import json
    cfg = Path(tmp) / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["notes", "docs/", ".md", "src/"]}}',
        encoding="utf-8")
    for a in agents or []:
        (cfg / "agents" / f"{a['name']}.json").write_text(json.dumps(a), encoding="utf-8")
    return tmp


_SCRIBE = {"name": "scribe", "call_name": "Quill", "model_tier": "haiku",
           "external_ok": False, "owns": ["notes.md"], "triggers": ["notes", "summar"],
           "must_read": [], "output_schema": "agent_report_v1", "category": "docs"}


class RepoRootRoutingTests(unittest.TestCase):
    """Fix 2: per-repo agent rosters are visible to routing."""

    def test_route_and_select_sees_repo_local_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(tmp, agents=[_SCRIBE])
            agent, decision = route_and_select(
                "Summarize the notes file", ["notes.md"], _AVAIL,
                repo_root=repo)
            self.assertEqual(agent["name"], "scribe")
            # trusted-only + review-only objective -> local advisory
            self.assertEqual(decision.provider, "ollama")
            self.assertEqual(decision.mode, "advisory")


class _AdvisoryDraftWorker:
    """Produces a draft, writes nothing (legitimate advisory behavior)."""
    def run(self, **kwargs):
        return {"report": _report(files_changed=[])}
    def rollback(self):
        return []


class _BadWriteWorker:
    """Writes a real file with a SYNTAX ERROR, supports real rollback."""
    def __init__(self, repo_root):
        self._p = Path(repo_root) / "src" / "broken.py"
        self.rollback_failures = []
    def run(self, **kwargs):
        self._p.parent.mkdir(parents=True, exist_ok=True)
        self._p.write_text("def broken(:\n", encoding="utf-8")
        return {"report": _report(files_changed=["src/broken.py"])}
    def rollback(self):
        if self._p.exists():
            self._p.unlink()
        return [str(self._p)]


class WroteFieldTests(unittest.TestCase):
    """Fix 1: result['wrote'] is disk ground truth in every outcome."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_advisory_draft_reports_wrote_empty(self):
        repo = _make_repo(self._tmp.name, agents=[_SCRIBE])
        with mock.patch("daedalus.providers.get_provider",
                        return_value=_AdvisoryDraftWorker()):
            r = offload("Summarize the notes file", repo, ["notes.md"],
                        live=True, availability=_AVAIL)
        self.assertEqual(r["mode"], "advisory")
        self.assertEqual(r["action"], "offloaded")   # a draft IS a success
        self.assertEqual(r["wrote"], [])             # ...but nothing was written

    def test_rolled_back_escalation_reports_wrote_empty(self):
        builder = {"name": "builder", "call_name": "Brick", "model_tier": "haiku",
                   "external_ok": True, "owns": ["src/"], "triggers": ["helper", "greeting", "string"],
                   "must_read": [], "output_schema": "agent_report_v1", "category": "implementation"}
        repo = _make_repo(self._tmp.name, agents=[builder])
        worker = _BadWriteWorker(repo)
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload("Fix the greeting string in the helper", repo,
                        ["src/broken.py"], live=True, availability=_AVAIL)
        if r["mode"] != "write":       # routing changed -> this test is moot
            self.skipTest(f"routed {r['mode']}, need write")
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertEqual(r["wrote"], [])             # rollback restored the disk
        self.assertFalse((Path(repo) / "src" / "broken.py").exists())


class _DirtyRollbackWorker:
    """Writes a broken file and then FAILS to roll it back -- the never-before-
    exercised dirty_unreverted path (Coffee-retro trust gap)."""
    def __init__(self, repo_root):
        self._abs = Path(repo_root) / "src" / "broken.py"
        self.rollback_failures = []
    def run(self, **kwargs):
        self._abs.parent.mkdir(parents=True, exist_ok=True)
        self._abs.write_text("def broken(:\n", encoding="utf-8")  # syntax error -> gate fails
        return {"report": _report(files_changed=["src/broken.py"])}
    def rollback(self):
        self.rollback_failures = [str(self._abs)]   # pretend revert failed
        return []


class DirtyRollbackTests(unittest.TestCase):
    """When rollback can't revert a bad write, the leftover must be surfaced
    (dirty_unreverted) and reflected honestly in 'wrote' -- not silently lost."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_unrevertable_bad_write_is_surfaced(self):
        builder = {"name": "builder", "call_name": "Brick", "model_tier": "haiku",
                   "external_ok": True, "owns": ["src/"], "triggers": ["helper", "greeting", "string"],
                   "must_read": [], "output_schema": "agent_report_v1", "category": "implementation"}
        repo = _make_repo(self._tmp.name, agents=[builder])
        worker = _DirtyRollbackWorker(repo)
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload("Fix the greeting string in the helper", repo,
                        ["src/broken.py"], live=True, availability=_AVAIL)
        if r["mode"] != "write":
            self.skipTest(f"routed {r['mode']}, need write")
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertIn("dirty_unreverted", r)                 # leftover surfaced
        self.assertEqual(r["wrote"], ["src/broken.py"])      # honest: still on disk
        self.assertTrue((Path(repo) / "src" / "broken.py").exists())


class RewriteCreateTests(unittest.TestCase):
    """Fix 3: the rewrite path can CREATE a new file (greenfield)."""

    def _provider(self):
        from daedalus.providers.ollama import OllamaProvider
        return OllamaProvider()

    def test_create_new_file_then_rollback_deletes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._provider()
            with mock.patch("daedalus.providers.ollama.native_chat",
                            return_value={"role": "assistant",
                                          "content": '{"content": "# Watering Tips\\n\\nWater at dawn.\\n"}'}):
                report = p._run_rewrite("Create a watering tips doc", tmp,
                                        ["docs/tips.md"], None, 60, None)
            target = Path(tmp) / "docs" / "tips.md"
            self.assertEqual(report["files_changed"], ["docs/tips.md"])
            self.assertTrue(target.exists())
            self.assertIn("Water at dawn", target.read_text(encoding="utf-8"))
            # rollback removes the created file AND the created dir
            p.rollback()
            self.assertFalse(target.exists())
            self.assertFalse(target.parent.exists())

    def test_create_refuses_empty_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._provider()
            with mock.patch("daedalus.providers.ollama.native_chat",
                            return_value={"role": "assistant", "content": '{"content": ""}'}):
                report = p._run_rewrite("Create a doc", tmp, ["docs/x.md"], None, 60, None)
            self.assertEqual(report["files_changed"], [])
            self.assertFalse((Path(tmp) / "docs" / "x.md").exists())


class HtmlJsGateTests(unittest.TestCase):
    """Fix 4: .html truncation tripwire and .js node --check gate."""

    def _verify_one(self, repo, rel):
        return verify(_report(files_changed=[rel]), repo,
                      disk_changed=[rel], require_changes=True)

    def test_truncated_html_fails_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.html").write_text(
                "<title>x</title><script>let a = 1;", encoding="utf-8")  # unclosed script
            vr = self._verify_one(tmp, "app.html")
            self.assertFalse(vr.ok)
            self.assertIn("htmlcheck:app.html", vr.failed)

    def test_balanced_html_passes_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.html").write_text(
                "<title>x</title><style>b{}</style><script>let a=1;</script>",
                encoding="utf-8")
            vr = self._verify_one(tmp, "app.html")
            self.assertTrue(vr.ok, vr.as_dict())

    def test_bad_js_fails_when_node_available(self):
        import shutil as _sh
        if not _sh.which("node"):
            self.skipTest("node not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.js").write_text("function ( { nope", encoding="utf-8")
            vr = self._verify_one(tmp, "app.js")
            self.assertFalse(vr.ok)
            self.assertIn("jscheck:app.js", vr.failed)

    def test_js_gate_skips_cleanly_without_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.js").write_text("syntactically ( broken", encoding="utf-8")
            with mock.patch("shutil.which", return_value=None):
                vr = self._verify_one(tmp, "app.js")
            self.assertTrue(vr.ok, vr.as_dict())


if __name__ == "__main__":
    unittest.main()
