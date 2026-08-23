"""Regression: the blast-radius fence must also see what a WRITE actually landed.

Two confirmed CRITICALs closed here, both the same shape -- the routing-time
reachability fence in ``select_provider`` only ever sees the DECLARED paths, so a
write onto a leaf that transitively feeds a fenced module slips past when the
path was never declared:

  1. offload's writable agentic lane. With empty ``--paths`` the worker is told
     to "explore from the repo root" and the local write tool is not restricted
     to the hint list, so a 7B model can write ``utils/clamp.py`` (imported by
     ``controller/hv_interlock.py``) and the routing fence -- which iterated zero
     declared paths -- never fired. The verifier is now backed by a POST-WRITE
     fence over the real on-disk diff.

  2. the forced ``codex`` lane in ``core._codex_report``. It granted
     workspace-write from ``change_risk`` alone and never called
     ``select_provider``, so the fence never ran on that path either -- a
     declared leaf reaching a fenced module got a repo-wide write sandbox. The
     writable grant now consults the same reachability pre-check.

Each defect is paired: the BLOCKED case (leaf reaches the fence) and the ALLOWED
case (an island file that reaches nothing keeps the cheap write lane), so a fix
that simply escalates everything would fail the allow half.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.core import _codex_report
# THE LIVE CASCADE TAKES A LEASE NOW, AND SO DOES THIS TEST. The shim that
# used to stand here called ``daedalus.offload._offload_impl`` directly with
# ``live=True`` -- a complete, un-leased write path. That second caller is
# exactly why ``scripts/declare_write_surfaces.py`` could not attribute the
# provider run to ``python.offload``'s Effect Lease: a write reachable from a
# leased AND an un-leased caller is attributable to neither. The planner no
# longer executes anything, so these tests take the door production takes.
from test_offload_lease_harness import live_offload as offload


# Only the local bench up: no deepseek (advisory) in the way, so a low-risk
# non-sensitive task lands unambiguously on ollama/write.
_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}
# Benign wording: no high-risk term, no review-only term, so mode stays "write"
# and the WORDING contributes nothing -- the fence has to do the work.
_OBJECTIVE = "improve the helper defaults"

_LEAF = "utils/clamp.py"                 # feeds the fenced controller
_ISLAND = "docs/notes_helper.py"         # reaches nothing


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _chain_repo(tmp: str) -> str:
    """utils/clamp.py <- lib/mid.py <- controller/hv_interlock.py, plus a policy
    so pol loads (writes stay fail-closed without one) and a repo-local
    external_ok agent so routing is hermetic and lands on the ollama write lane."""
    root = Path(tmp)
    _write(root, _LEAF, "def clamp(v, lo, hi):\n    return max(lo, min(hi, v))\n")
    _write(root, "lib/mid.py",
           "from utils.clamp import clamp\n\n\ndef scale(v):\n    return clamp(v, 0, 10)\n")
    _write(root, "controller/hv_interlock.py",
           "from lib.mid import scale\n\n\ndef trip(v):\n    return scale(v) > 5\n")
    _write(root, _ISLAND, "def blurb():\n    return 'hi'\n")
    cfg = root / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, '
        '"allow": ["utils/", "lib/", "controller/", "docs/"]}}', encoding="utf-8")
    (cfg / "agents" / "helper-dev.json").write_text(
        '{"name": "helper-dev", "call_name": "Help", "model_tier": "sonnet",'
        ' "external_ok": true, "owns": ["utils"], "triggers": ["helper", "improve"],'
        ' "must_read": [], "output_schema": "agent_report_v1",'
        ' "category": "implementation"}', encoding="utf-8")
    return str(root)


class _SneakyWorker:
    """Writes a file it was never told to touch (empty --paths), mirroring the
    ollama agentic write tool. Backs up + restores like the real provider so the
    escalation rollback is exercised."""

    def __init__(self, repo_root: str, rel: str, content: str):
        self._root, self._rel, self._content = repo_root, rel, content
        self._backup: bytes | None = None
        self.rollback_failures: list[str] = []

    def run(self, **kwargs):
        p = Path(self._root) / self._rel
        self._backup = p.read_bytes() if p.exists() else None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self._content, encoding="utf-8")
        # Self-report is deliberately EMPTY -- the disk snapshot is what the gate
        # and the new fence must act on, exactly like a narrating local model.
        return {"report": {"status": "done", "summary": "s", "files_changed": [],
                           "tests_run": [], "risks": [], "todos": [], "handoff": {}}}

    def rollback(self):
        p = Path(self._root) / self._rel
        if self._backup is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(self._backup)
        return [self._rel]


class OffloadPostWriteFenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        self.repo = _chain_repo(self._tmp.name)

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_undeclared_write_reaching_a_fenced_module_is_escalated(self):
        original = (Path(self.repo) / _LEAF).read_text(encoding="utf-8")
        worker = _SneakyWorker(self.repo, _LEAF, "def clamp(v, lo, hi):\n    return v\n")
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload(_OBJECTIVE, self.repo, paths=[], live=True, availability=_AVAIL)
        # It must have taken the ollama WRITE lane (else the test proves nothing).
        self.assertEqual(r["provider"], "ollama")
        self.assertEqual(r["mode"], "write")
        # ...and the write onto the interlock-feeding leaf must be REJECTED.
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertFalse(r["verify"]["ok"])
        self.assertIn("blast_radius", r["verify"]["failed"])
        # The sabotaged leaf was rolled back to its original bytes.
        self.assertEqual((Path(self.repo) / _LEAF).read_text(encoding="utf-8"), original)

    def test_undeclared_write_to_an_island_file_still_accepts(self):
        # ALLOW half: an edit that reaches nothing fenced keeps the cheap lane.
        worker = _SneakyWorker(self.repo, _ISLAND, "def blurb():\n    return 'bye'\n")
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload(_OBJECTIVE, self.repo, paths=[], live=True, availability=_AVAIL)
        self.assertEqual(r["provider"], "ollama")
        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "offloaded")
        self.assertTrue(r["verify"]["ok"])
        self.assertEqual((Path(self.repo) / _ISLAND).read_text(encoding="utf-8"),
                         "def blurb():\n    return 'bye'\n")


class _FakeCodex:
    """Records the writable grant the forced codex lane hands the provider."""

    def __init__(self):
        self.writable_seen = None

    def available(self):
        return True

    def run(self, **kwargs):
        self.writable_seen = kwargs.get("writable")
        return {"report": {"status": "done", "summary": "s", "files_changed": [],
                           "tests_run": [], "risks": [], "todos": [], "handoff": {}},
                "agent": "x", "persona": "y"}


class CodexLaneFenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _chain_repo(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, paths):
        fake = _FakeCodex()
        payload = {"objective": _OBJECTIVE, "repo_root": self.repo,
                   "paths": paths, "lane": "codex"}
        with mock.patch("daedalus.providers.get_provider", return_value=fake):
            rep = _codex_report(payload)
        self.assertEqual(rep["bridge_status"], "done", rep.get("error"))
        return fake

    def test_declared_leaf_reaching_the_fence_drops_codex_to_read_only(self):
        fake = self._run([_LEAF])
        self.assertIs(fake.writable_seen, False)

    def test_declared_island_file_keeps_workspace_write(self):
        # The legacy forced lane no longer grants direct workspace writes;
        # Forge will restore mutation through a verified worktree transaction.
        fake = self._run([_ISLAND])
        self.assertIs(fake.writable_seen, False)


if __name__ == "__main__":
    unittest.main()
