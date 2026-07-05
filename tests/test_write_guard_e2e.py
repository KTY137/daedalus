"""End-to-end coverage for the write-mode guard's fail-closed behavior.

Exercises the real seam (``daedalus.offload.offload``) for the invariants the
standing orders call out explicitly:

  1. A write-mode task whose provider narrates an edit but writes nothing to
     disk must escalate -- the verifier gate never trusts the self-report.
  2. A write-mode task whose provider genuinely writes an allowed file must be
     accepted (action: offloaded) and the file must exist on disk afterward.
  3. A write targeting a policy-protected/secret path must be refused and the
     file must be left untouched. This one goes through the REAL
     ``OllamaProvider`` (network never touched -- ``path_write_blocked`` short-
     circuits before any model call is made), so it is a genuine e2e check of
     ``daedalus.sensitivity.path_write_blocked``, not a re-test of a mock.
  0. Bonus: with NO project policy loaded at all, a write-mode task must be
     refused before the provider is even invoked (fail-closed on missing
     policy) -- this is the other half of "write-guard blocks real device/
     secret paths": no policy means no guards, so no live write is allowed.

No live Ollama/Claude is ever touched: cases 1 and 2 mock the provider
entirely, and case 3 relies on the write-guard rejecting the path before any
network call would happen.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.offload import offload

_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False}

# Objective wording chosen to score uniquely for docs-dev (external_ok: true,
# trigger "docs") in the built-in agents/ registry, so routing lands on a
# provider that is actually eligible to write (not the qa-critic fallback,
# which is external_ok: false and would divert to advisory/escalation).
_OBJECTIVE = "Update the docs notes file"
_ALLOWED_TARGET = "notes.md"
_SECRET_TARGET = "credentials.md"  # matches GENERIC_DENY_SUBSTRINGS "credential"


def _report(files_changed=None, status="done"):
    return {"status": status, "summary": "s", "files_changed": files_changed or [],
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class _NarratingWorker:
    """Self-reports an edit it never made."""

    def run(self, **kwargs):
        return {"report": _report(files_changed=[_ALLOWED_TARGET])}

    def rollback(self):
        return []


class _RealWritingWorker:
    """Actually writes the target file on disk."""

    def __init__(self, repo_root: str):
        self._repo_root = repo_root

    def run(self, **kwargs):
        p = Path(self._repo_root) / _ALLOWED_TARGET
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# notes\nreal content\n", encoding="utf-8")
        return {"report": _report(files_changed=[_ALLOWED_TARGET])}

    def rollback(self):
        return []


def _make_repo(tmp: str, allow=("notes.md", "docs/")) -> str:
    """A repo whose .agentenv config carries a (non-empty) policy so pol loads."""
    cfg_dir = Path(tmp) / ".agentenv"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "agentenv.json").write_text(
        json.dumps({"policy": {"default_deny": True, "allow": list(allow)}}),
        encoding="utf-8")
    return tmp


class WriteGuardE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_log = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig_log
        self._tmp.cleanup()

    # -- 0. no policy loaded at all -> refuse before the provider ever runs --

    def test_no_policy_loaded_refuses_live_write(self):
        """No .agentenv config in the repo -> resolve_project returns None ->
        pol stays None -> offload MUST refuse the write before invoking any
        provider (fail-closed: guards are only real when a policy is loaded)."""
        repo = self._tmp.name  # no .agentenv/ created here at all
        with mock.patch("daedalus.providers.get_provider") as get_provider:
            r = offload(_OBJECTIVE, repo, paths=[_ALLOWED_TARGET],
                        live=True, availability=_AVAIL)
        get_provider.assert_not_called()
        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "escalate_to_claude")
        self.assertIn("no project policy loaded", r["note"])
        self.assertFalse((Path(repo) / _ALLOWED_TARGET).exists())

    # -- 1. narrated but no disk write -> escalate, never fake-accept --------

    def test_narrated_no_disk_write_escalates(self):
        repo = _make_repo(self._tmp.name)
        with mock.patch("daedalus.providers.get_provider",
                        return_value=_NarratingWorker()):
            r = offload(_OBJECTIVE, repo, paths=[_ALLOWED_TARGET],
                        live=True, availability=_AVAIL)
        self.assertEqual(r["mode"], "write")
        self.assertNotEqual(r["action"], "offloaded")
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertFalse(r["verify"]["ok"])
        self.assertIn("did_work", r["verify"]["failed"])
        self.assertFalse((Path(repo) / _ALLOWED_TARGET).exists())

    # -- 2. a real write to an allowed path -> accepted and persisted -------

    def test_real_write_to_allowed_path_is_accepted_and_persisted(self):
        repo = _make_repo(self._tmp.name)
        worker = _RealWritingWorker(repo)
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload(_OBJECTIVE, repo, paths=[_ALLOWED_TARGET],
                        live=True, availability=_AVAIL)
        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "offloaded")
        self.assertTrue(r["verify"]["ok"])
        target = Path(repo) / _ALLOWED_TARGET
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "# notes\nreal content\n")

    # -- 3. a genuinely denied path -> refused by the REAL write-guard ------

    def test_secret_path_write_is_blocked_and_left_untouched(self):
        """Uses the real OllamaProvider (daedalus.providers.get_provider is NOT
        mocked here) so this exercises the actual path_write_blocked() guard in
        daedalus/providers/ollama.py::_run_rewrite. 'credentials.md' matches
        GENERIC_DENY_SUBSTRINGS ('credential'), which load_policy ALWAYS unions
        in regardless of the repo's own policy -- so path_write_blocked trips
        before the provider ever makes a model call (no chat_completion/
        chat_raw is reached), keeping this deterministic and network-free."""
        repo = _make_repo(self._tmp.name)
        target = Path(repo) / _SECRET_TARGET
        original = "classified: do-not-touch\n"
        target.write_text(original, encoding="utf-8")

        r = offload(_OBJECTIVE, repo, paths=[_SECRET_TARGET],
                    live=True, availability=_AVAIL)

        self.assertEqual(r["mode"], "write")
        self.assertTrue(r["sensitive"])  # denylisted path fragment classifies as sensitive
        self.assertNotEqual(r["action"], "offloaded")
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        self.assertFalse(r["verify"]["ok"])
        self.assertIn("did_work", r["verify"]["failed"])
        # The file must be untouched -- the write-guard refused it, not just
        # the verifier catching it after the fact.
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertEqual(r["report"]["files_changed"], [])


if __name__ == "__main__":
    unittest.main()
