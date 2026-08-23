"""Regression: the 'fake offload' fail-open hole.

A narrating local model returns a report claiming ``files_changed:["x"]`` while
writing NOTHING to disk. The write-mode ``require_changes`` gate used to trust
that self-report and ACCEPT the no-op (action:"offloaded", verify.ok:true) --
fake savings, zero work. The gate must instead verify a REAL on-disk change.

These tests mock the provider so nothing touches live Ollama.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.verifier import verify
# THE LIVE CASCADE TAKES A LEASE NOW, AND SO DOES THIS TEST. The shim that
# used to stand here called ``daedalus.offload._offload_impl`` directly with
# ``live=True`` -- a complete, un-leased write path. That second caller is
# exactly why ``scripts/declare_write_surfaces.py`` could not attribute the
# provider run to ``python.offload``'s Effect Lease: a write reachable from a
# leased AND an un-leased caller is attributable to neither. The planner no
# longer executes anything, so these tests take the door production takes.
from test_offload_lease_harness import live_offload as offload


_OBJECTIVE = "Add a docstring to the scan panel"
_TARGET = "TCT_app/gui/scan_panel.py"          # gui path -> writable, routes to ollama write
_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False}


def _report(files_changed=None, status="done"):
    return {"status": status, "summary": "s", "files_changed": files_changed or [],
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class _NarratingWorker:
    """Self-reports an edit it never made -- the exact fake-offload repro."""

    def run(self, **kwargs):
        return {"report": _report(files_changed=[_TARGET])}

    def rollback(self):
        return []


class _RealWritingWorker:
    """Actually writes the target file on disk (the legitimate allow case)."""

    def __init__(self, repo_root: str):
        self._repo_root = repo_root

    def run(self, **kwargs):
        p = Path(self._repo_root) / _TARGET
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('"""scan panel."""\nx = 1\n', encoding="utf-8")
        return {"report": _report(files_changed=[_TARGET])}

    def rollback(self):
        return []


def _make_repo(tmp: str) -> str:
    """A repo whose .agentenv config carries a (non-empty) policy so pol loads,
    plus a repo-local agent so routing is HERMETIC (independent of the global
    registry -- repo_root now threads into routing, and a repo without its own
    agents would fall back to the generic templates crew)."""
    cfg_dir = Path(tmp) / ".agentenv"
    (cfg_dir / "agents").mkdir(parents=True, exist_ok=True)
    (cfg_dir / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["TCT_app/"]}}', encoding="utf-8")
    (cfg_dir / "agents" / "gui-dev.json").write_text(
        '{"name": "gui-dev", "call_name": "Pix", "model_tier": "sonnet",'
        ' "external_ok": true, "owns": ["TCT_app/gui"], "triggers": ["docstring", "panel"],'
        ' "must_read": [], "output_schema": "agent_report_v1", "category": "implementation"}',
        encoding="utf-8")
    return tmp


class VerifierDiskChangeUnitTests(unittest.TestCase):
    """The gate must not fall back to the untrusted self-report."""

    # The real repro path. It WAS chosen as a .md "so no extra checks" -- that
    # is no longer true: prose now gets a fact-preservation check, and a prose
    # file with no before-image is refused rather than waved through. These
    # cases are about the did_work gate, so they declare the file as created
    # (``None``), which is the honest before-image for a path the test invents.
    _DOC = "notes.md"

    def test_disk_evidence_overrides_a_lying_self_report(self):
        # The report CLAIMS an edit, but the caller's disk snapshot proves
        # nothing changed -> the self-report is ignored and the gate fails.
        vr = verify(_report(files_changed=[self._DOC]), ".",
                    require_changes=True, disk_changed=[])
        self.assertFalse(vr.ok)
        self.assertIn("did_work", vr.failed)

    def test_real_disk_change_passes(self):
        vr = verify(_report(files_changed=[self._DOC]), ".",
                    require_changes=True, disk_changed=[self._DOC],
                    prose_before={self._DOC: None})
        self.assertTrue(vr.ok)


class FakeOffloadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        self.repo = _make_repo(self._tmp.name)

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_fake_offload_narrated_but_no_disk_write_escalates(self):
        with mock.patch("daedalus.providers.get_provider",
                        return_value=_NarratingWorker()):
            r = offload(_OBJECTIVE, self.repo, paths=[_TARGET],
                        live=True, availability=_AVAIL)
        # Must NOT accept a no-op that only claimed to edit.
        self.assertEqual(r["mode"], "write")
        self.assertNotEqual(r["action"], "offloaded")
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertFalse(r["verify"]["ok"])
        self.assertIn("did_work", r["verify"]["failed"])
        # And the file genuinely was never written.
        self.assertFalse((Path(self.repo) / _TARGET).exists())

    def test_real_disk_write_is_accepted(self):
        worker = _RealWritingWorker(self.repo)
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload(_OBJECTIVE, self.repo, paths=[_TARGET],
                        live=True, availability=_AVAIL)
        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "offloaded")
        self.assertTrue(r["verify"]["ok"])
        self.assertTrue((Path(self.repo) / _TARGET).exists())


if __name__ == "__main__":
    unittest.main()
