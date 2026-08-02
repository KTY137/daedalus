"""Fail-close the routed write lane on rollback capability (Momus CRITICAL #1).

The verify-fail path in ``offload`` undoes a bad write via ``worker.rollback()``,
but only the ollama provider implements rollback -- ``CodexCLIProvider`` has
none. Before this gate, a routed codex write-mode task received
``writable=True``, so a verify-fail left the primary checkout dirty while the
result reported ``rolled_back=[]`` with no flag.

Now a provider may hold ``writable=True`` ONLY if it exposes a callable
``rollback()``. Otherwise the grant is forced to False with an EXPLICIT
``mutation_blocked`` notice + ``needs_stronger_lane`` marker (mirroring
``core._codex_report``'s forced-codex stamp), and the write-mode verify gate
then escalates the run -- never a silent advisory downgrade, never a dirty
checkout.

Also covered: ``.daedalus_worktrees`` is excluded from the whole-repo snapshot
so candidate worktrees never poison write attribution.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.offload import _SNAPSHOT_SKIP, _offload_impl, _repo_snapshot
def offload(*args, **kwargs):
    """Exercise the pre-lease cascade in focused unit tests.

    Public live calls are covered separately by test_leased_offload.py. These
    tests isolate routing/verification behavior and provide the private
    TaskAttempt workspace grant required by the internal implementation.
    """
    repo_root = kwargs.get("repo_root")
    if repo_root is None and len(args) > 1:
        repo_root = args[1]
    kwargs.setdefault("_attempt_workspace", {"worktree": str(repo_root)})
    return _offload_impl(*args, **kwargs)


# Benign wording (risk stays low -> mode "write"); non-sensitive docs path.
_OBJECTIVE = "improve the helper defaults"
_TARGET = "docs/notes_helper.py"

# Bench down, deepseek off -> non-sensitive low-risk lands on codex_cli/write.
_AVAIL_CODEX = {"claude_cli": True, "ollama": False, "deepseek": False, "codex_cli": True}
# Bench up, codex off -> same task lands on ollama/write.
_AVAIL_OLLAMA = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}

_REPORT = {"status": "done", "summary": "s", "files_changed": [],
           "tests_run": [], "risks": [], "todos": [], "handoff": {}}


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp: str) -> str:
    """One benign docs module + a policy (writes are refused without one) + a
    repo-local external_ok agent so routing is hermetic."""
    root = Path(tmp)
    _write(root, _TARGET, "def blurb():\n    return 'hi'\n")
    cfg = root / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["docs/"]}}', encoding="utf-8")
    (cfg / "agents" / "helper-dev.json").write_text(
        '{"name": "helper-dev", "call_name": "Help", "model_tier": "sonnet",'
        ' "external_ok": true, "owns": ["docs"], "triggers": ["helper", "improve"],'
        ' "must_read": [], "output_schema": "agent_report_v1",'
        ' "category": "implementation"}', encoding="utf-8")
    return str(root)


class _NoRollbackWorker:
    """Records the writable grant; cannot roll back (the codex_cli shape)."""

    def __init__(self):
        self.writable_seen = None

    def run(self, **kwargs):
        self.writable_seen = kwargs.get("writable")
        return {"report": dict(_REPORT)}


class _RollbackWorker:
    """Records the writable grant, writes the declared target, can roll back."""

    def __init__(self, repo_root: str, rel: str):
        self._root, self._rel = repo_root, rel
        self._backup: bytes | None = None
        self.writable_seen = None
        self.rollback_failures: list[str] = []

    def run(self, **kwargs):
        self.writable_seen = kwargs.get("writable")
        p = Path(self._root) / self._rel
        self._backup = p.read_bytes() if p.exists() else None
        p.write_text("def blurb():\n    return 'bye'\n", encoding="utf-8")
        return {"report": dict(_REPORT)}

    def rollback(self):
        p = Path(self._root) / self._rel
        if self._backup is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(self._backup)
        return [self._rel]


class WritableFailCloseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        self.repo = _repo(self._tmp.name)

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def _offload(self, worker, availability):
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            return offload(_OBJECTIVE, self.repo, paths=[_TARGET], live=True,
                           availability=availability)

    def test_codex_write_without_rollback_is_forced_advisory_and_escalates(self):
        original = (Path(self.repo) / _TARGET).read_text(encoding="utf-8")
        worker = _NoRollbackWorker()
        r = self._offload(worker, _AVAIL_CODEX)
        # It must have taken the codex WRITE lane (else the test proves nothing).
        self.assertEqual(r["provider"], "codex_cli")
        self.assertEqual(r["mode"], "write")
        # The grant handed to the provider was forced OFF...
        self.assertIs(worker.writable_seen, False)
        # ...with an explicit notice + escalation marker, never silently.
        self.assertIn("advisory-only until Forge", r["mutation_blocked"])
        self.assertIn("no rollback", r["mutation_blocked"])
        self.assertIs(r["needs_stronger_lane"], True)
        # The write-mode gate escalates (no on-disk change), checkout untouched.
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertEqual(r["rolled_back"], [])
        self.assertNotIn("dirty_unreverted", r)
        self.assertEqual((Path(self.repo) / _TARGET).read_text(encoding="utf-8"),
                         original)

    def test_ollama_write_grant_is_unchanged(self):
        worker = _RollbackWorker(self.repo, _TARGET)
        r = self._offload(worker, _AVAIL_OLLAMA)
        self.assertEqual(r["provider"], "ollama")
        self.assertEqual(r["mode"], "write")
        self.assertIs(worker.writable_seen, True)
        self.assertNotIn("mutation_blocked", r)
        self.assertNotIn("needs_stronger_lane", r)
        self.assertEqual(r["action"], "offloaded")
        self.assertEqual(r["wrote"], [_TARGET])

    def test_provider_with_rollback_keeps_the_write_grant(self):
        # The gate keys off CAPABILITY, not provider name: a rollback-capable
        # worker on the codex route keeps writable=True.
        worker = _RollbackWorker(self.repo, _TARGET)
        r = self._offload(worker, _AVAIL_CODEX)
        self.assertEqual(r["provider"], "codex_cli")
        self.assertEqual(r["mode"], "write")
        self.assertIs(worker.writable_seen, True)
        self.assertNotIn("mutation_blocked", r)
        self.assertNotIn("needs_stronger_lane", r)
        self.assertEqual(r["action"], "offloaded")


class SnapshotSkipTests(unittest.TestCase):
    def test_daedalus_worktrees_is_skipped(self):
        self.assertIn(".daedalus_worktrees", _SNAPSHOT_SKIP)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "a.py", "x = 1\n")
            _write(root, ".daedalus_worktrees/cand1/a.py", "x = 2\n")
            snap = _repo_snapshot(tmp)
            self.assertIn("a.py", snap)
            self.assertFalse(any(k.startswith(".daedalus_worktrees") for k in snap),
                             snap)


if __name__ == "__main__":
    unittest.main()
