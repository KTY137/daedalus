"""The slice→offload wire (Horizon Phase 2, static-only).

The seam under test: ``offload()`` builds a GATED distilled slice of the
declared targets and hands it to the LOCAL worker only. The invariants, each
with its own case below:

  * trusted-lane exclusivity -- the slice is built inside the ollama branch
    alone; an external lane (deepseek/codex) never triggers a build and its
    result carries no slice_context block at all;
  * default OFF -- OFFLOAD_SLICE_TOKENS unset/0 injects nothing and says so
    (the wire ships dark until the live A/B landing gate flips it);
  * rewrite-bound tasks get NEIGHBORHOOD-ONLY context (the prompt already
    carries the file body; the slice must not pay for a duplicate), while
    agentic tasks get the full slice, capped at MAX_REWRITE_FILES targets;
  * fail-closed on content -- a focus file the egress gate refuses injects
    NOTHING, with the reason on the result;
  * fail-open on build -- a broken slicer never blocks the task, and the
    failure is reported, never silent;
  * worker-reported window drops surface as slice_context.dropped_for_window.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from test_offload_lease_harness import live_offload as offload


_AVAIL_OLLAMA = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": False}
_AVAIL_DEEPSEEK = {"claude_cli": True, "ollama": False, "deepseek": True, "codex_cli": False}
# Benign write wording (same as the blast-radius tests): lands ollama/write.
_OBJECTIVE = "improve the helper defaults"

_BODY_LINE = "return max(lo, min(hi, v))"  # distinctive: only in app/util.py's body


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp: str) -> str:
    """app/util.py <- app/main.py (a caller for the slice), two extra leaves for
    the >MAX_REWRITE_FILES agentic case, one secret-bearing file for the gate
    case, plus the policy + hermetic agent the live write lane requires."""
    root = Path(tmp)
    _write(root, "app/util.py",
           f"def helper_util(v, lo, hi):\n    {_BODY_LINE}\n")
    _write(root, "app/main.py",
           "from app.util import helper_util\n\n\ndef go(v):\n    return helper_util(v, 0, 9)\n")
    _write(root, "app/extra_one.py", "def one():\n    return 1\n")
    _write(root, "app/extra_two.py", "def two():\n    return 2\n")
    # Secret floor bait: content (not path) carries the credential shape.
    _write(root, "app/values.py",
           'LIMIT = 9\nAWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    cfg = root / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    (cfg / "agentenv.json").write_text(
        '{"policy": {"default_deny": true, "allow": ["app/", "docs/"]}}',
        encoding="utf-8")
    (cfg / "agents" / "helper-dev.json").write_text(
        '{"name": "helper-dev", "call_name": "Help", "model_tier": "sonnet",'
        ' "external_ok": true, "owns": ["app"], "triggers": ["helper", "improve"],'
        ' "must_read": [], "output_schema": "agent_report_v1",'
        ' "category": "implementation"}', encoding="utf-8")
    return str(root)


class _RecordingWorker:
    """Records run kwargs; optionally lands a real disk change so the write
    gate passes; optionally smuggles a handoff block into the report."""

    def __init__(self, repo_root: str, write_rel: str | None = None,
                 handoff: dict | None = None):
        self.kwargs: dict | None = None
        self._root, self._rel, self._handoff = repo_root, write_rel, handoff or {}
        self.rollback_failures: list[str] = []

    def run(self, **kwargs):
        self.kwargs = kwargs
        if self._rel:
            p = Path(self._root) / self._rel
            p.write_text(p.read_text(encoding="utf-8") + "\n# touched\n",
                         encoding="utf-8")
        return {"report": {"status": "done", "summary": "s",
                           "files_changed": [self._rel] if self._rel else [],
                           "tests_run": [], "risks": [], "todos": [],
                           "handoff": dict(self._handoff)}}

    def rollback(self):
        return []


class OffloadSliceContextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_log = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        self.repo = _repo(self._tmp.name)
        # Isolate the budget env var per test.
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("OFFLOAD_SLICE_TOKENS", None)

    def tearDown(self):
        self._env.stop()
        metrics.LOG = self._orig_log
        self._tmp.cleanup()

    def _offload(self, paths, avail=_AVAIL_OLLAMA, worker=None):
        worker = worker or _RecordingWorker(self.repo, write_rel=(paths[0] if paths else None))
        with mock.patch("daedalus.providers.get_provider", return_value=worker):
            r = offload(_OBJECTIVE, self.repo, paths=paths, live=True,
                        availability=avail)
        return r, worker

    def test_rewrite_bound_slice_is_neighborhood_only(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "2000"
        r, w = self._offload(["app/util.py"])
        self.assertEqual(r["provider"], "ollama")
        self.assertEqual(r["mode"], "write")
        texts = w.kwargs.get("slice_texts")
        self.assertIsNotNone(texts, "worker never received the gated slice")
        self.assertIn("app/util.py", texts)
        # Neighborhood present, focus body omitted (it is already in the prompt).
        self.assertIn("CALLERS", texts["app/util.py"])
        self.assertIn("body omitted", texts["app/util.py"])
        self.assertNotIn(_BODY_LINE, texts["app/util.py"])
        meta = r["slice_context"]
        self.assertTrue(meta["injected"])
        self.assertEqual(meta["targets"][0]["status"], "injected")
        self.assertGreater(meta["targets"][0]["slice_tokens"], 0)

    def test_agentic_gets_full_slice_capped_at_three_targets(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "4000"
        paths = ["app/util.py", "app/main.py", "app/extra_one.py", "app/extra_two.py"]
        r, w = self._offload(paths)
        self.assertEqual(r["provider"], "ollama")
        texts = w.kwargs.get("slice_texts")
        self.assertIsNotNone(texts)
        # >MAX_REWRITE_FILES declared -> agentic lane -> full slice, first 3 only.
        self.assertEqual(len(texts), 3)
        self.assertIn(_BODY_LINE, texts["app/util.py"])
        self.assertTrue(r["slice_context"]["injected"])

    def test_default_off_injects_nothing_and_says_so(self):
        r, w = self._offload(["app/util.py"])
        self.assertEqual(r["provider"], "ollama")
        self.assertNotIn("slice_texts", w.kwargs)
        meta = r["slice_context"]
        self.assertFalse(meta["injected"])
        self.assertIn("OFFLOAD_SLICE_TOKENS", meta["reason"])

    def test_no_declared_paths_reports_reason(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "2000"
        r, w = self._offload([])
        self.assertEqual(r["provider"], "ollama")
        self.assertNotIn("slice_texts", w.kwargs)
        self.assertFalse(r["slice_context"]["injected"])
        self.assertIn("no declared paths", r["slice_context"]["reason"])

    def test_external_lane_never_builds_a_slice(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "2000"
        r, w = self._offload(["app/util.py"], avail=_AVAIL_DEEPSEEK,
                             worker=_RecordingWorker(self.repo))
        self.assertEqual(r["provider"], "deepseek")
        self.assertNotIn("slice_texts", w.kwargs)
        # Not even a metadata block: the external lane's result is untouched.
        self.assertNotIn("slice_context", r)

    def test_focus_withheld_by_gate_injects_nothing(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "2000"
        r, w = self._offload(["app/values.py"])
        self.assertEqual(r["provider"], "ollama")
        self.assertNotIn("slice_texts", w.kwargs)
        meta = r["slice_context"]
        self.assertFalse(meta["injected"])
        entry = meta["targets"][0]
        self.assertEqual(entry["status"], "skipped")
        self.assertIn("focus withheld", entry["reason"])

    def test_slice_build_failure_fails_open_and_is_reported(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "2000"
        # Break the SLICER, not cached_index: the routing precheck and the
        # post-write blast-radius fence share cached_index, and poisoning it
        # makes the fence (correctly) fail-closed escalate the write -- which
        # would test the fence, not this seam's fail-open.
        with mock.patch("daedalus.structcore.slice.semantic_slice",
                        side_effect=RuntimeError("boom")):
            r, w = self._offload(["app/util.py"])
        self.assertEqual(r["provider"], "ollama")
        self.assertNotIn("slice_texts", w.kwargs)
        # The task itself proceeded (worker ran, write landed, gate passed).
        self.assertEqual(r["action"], "offloaded")
        self.assertIn("slice build failed", r["slice_context"]["reason"])

    def test_worker_window_drops_surface_on_the_result(self):
        os.environ["OFFLOAD_SLICE_TOKENS"] = "2000"
        worker = _RecordingWorker(
            self.repo, write_rel="app/util.py",
            handoff={"slice_context_dropped": ["app/util.py"]})
        r, _ = self._offload(["app/util.py"], worker=worker)
        self.assertEqual(r["slice_context"]["dropped_for_window"], ["app/util.py"])


if __name__ == "__main__":
    unittest.main()
