"""Tests for the full-file-rewrite write path (OllamaProvider._run_rewrite).

The live benchmark showed 7B models never emit write_file tool calls; the
rewrite path is the fix. Everything here is offline: the model call is mocked.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus.providers.ollama import OllamaProvider


def _repo(files: dict[str, str]) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    for rel, content in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


def _model_returns(content: str):
    """Patch the module-level native_chat to return an assistant message whose
    content is {'content': ...} (the shape _run_rewrite parses)."""
    return mock.patch(
        "daedalus.providers.ollama.native_chat",
        return_value={"role": "assistant", "content": json.dumps({"content": content})},
    )


ORIGINAL = "def add(a, b):\n    return a + b\n"
EDITED = 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n'


class RewriteApplyTests(unittest.TestCase):
    def test_rewrite_applies_and_reports(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED):
            p = OllamaProvider()
            report = p._run_rewrite("Add docstrings", d, ["src/calc.py"], None, 60, None)
            self.assertEqual(report["files_changed"], ["src/calc.py"])
            self.assertEqual(report["status"], "done")
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), EDITED)

    def test_identical_content_is_a_noop(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(ORIGINAL):
            report = OllamaProvider()._run_rewrite("Add docstrings", d, ["src/calc.py"], None, 60, None)
        self.assertEqual(report["files_changed"], [])
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("no change produced", report["summary"])

    def test_truncation_guard_refuses_short_result(self):
        long_src = ORIGINAL * 20
        with _repo({"src/calc.py": long_src}) as d, _model_returns("def add(a, b):\n"):
            report = OllamaProvider()._run_rewrite("Refactor", d, ["src/calc.py"], None, 60, None)
            self.assertEqual(report["files_changed"], [])
            self.assertIn("suspected truncation", report["summary"])
            # original untouched
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), long_src)

    def test_elision_marker_is_rejected(self):
        elided = ORIGINAL + "\n# ... rest of the file unchanged\n"
        with _repo({"src/calc.py": ORIGINAL * 3}) as d, _model_returns(elided):
            report = OllamaProvider()._run_rewrite("Refactor", d, ["src/calc.py"], None, 60, None)
            self.assertEqual(report["files_changed"], [])
            self.assertIn("elision marker", report["summary"])
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), ORIGINAL * 3)

    def test_preexisting_marker_text_is_not_a_false_positive(self):
        # the file already says "remains unchanged" -- keeping it must not reject
        src = ORIGINAL + "# behavior remains unchanged since v1\n"
        edited = 'def add(a, b):\n    """Add."""\n    return a + b\n# behavior remains unchanged since v1\n'
        with _repo({"src/calc.py": src}) as d, _model_returns(edited):
            report = OllamaProvider()._run_rewrite("Add docstring", d, ["src/calc.py"], None, 60, None)
            self.assertEqual(report["files_changed"], ["src/calc.py"])

    def test_protected_path_is_skipped(self):
        # default policy always denies secret-ish paths
        with _repo({"secret_keys.py": ORIGINAL}) as d, _model_returns(EDITED):
            report = OllamaProvider()._run_rewrite("Edit", d, ["secret_keys.py"], None, 60, None)
            self.assertEqual(report["files_changed"], [])
            self.assertIn("protected path", report["summary"])
            self.assertEqual((Path(d) / "secret_keys.py").read_text(encoding="utf-8"), ORIGINAL)

    def test_path_escape_is_skipped(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED):
            report = OllamaProvider()._run_rewrite("Edit", d, ["../outside.py"], None, 60, None)
        self.assertEqual(report["files_changed"], [])
        self.assertIn("outside repo", report["summary"])

    def test_rollback_restores_original(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED):
            p = OllamaProvider()
            report = p._run_rewrite("Add docstrings", d, ["src/calc.py"], None, 60, None)
            self.assertEqual(report["files_changed"], ["src/calc.py"])
            restored = p.rollback()
            self.assertEqual(restored, [str((Path(d) / "src/calc.py").resolve())])
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), ORIGINAL)


class RunRoutingTests(unittest.TestCase):
    # Both paths now share native_chat, so the branch is asserted from the CALL:
    # the rewrite path sends force_json=True and NO tools; the agentic loop sends
    # tools and no force_json. That is the routing branch's semantics, observable
    # in the request -- a stronger check than the old distinct-symbol trick.
    def test_writable_scoped_task_uses_rewrite_not_tool_loop(self):
        agent = {"name": "docs-dev", "call_name": "Lucia"}
        with _repo({"src/calc.py": ORIGINAL}) as d, mock.patch(
            "daedalus.providers.ollama.native_chat",
            return_value={"role": "assistant", "content": json.dumps({"content": EDITED})},
        ) as nc:
            out = OllamaProvider().run(objective="Add docstrings", repo_root=d,
                                       paths=["src/calc.py"], agent=agent, writable=True)
        self.assertEqual(out["report"]["files_changed"], ["src/calc.py"])
        # single rewrite call: force_json, and the tool loop did NOT run (no tools)
        self.assertEqual(nc.call_count, 1)
        self.assertTrue(nc.call_args.kwargs.get("force_json"))
        self.assertNotIn("tools", nc.call_args.kwargs)

    def test_advisory_task_still_uses_agentic_loop(self):
        agent = {"name": "docs-dev", "call_name": "Lucia"}
        final = {"status": "needs_review", "summary": "reviewed", "files_changed": [],
                 "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        with _repo({"src/calc.py": ORIGINAL}) as d, mock.patch(
            "daedalus.providers.ollama.native_chat",
            return_value={"role": "assistant", "content": json.dumps(final)},
        ) as nc:
            out = OllamaProvider().run(objective="Review the calc helpers", repo_root=d,
                                       paths=["src/calc.py"], agent=agent, writable=False)
        self.assertTrue(nc.called)
        # agentic loop ran (tools passed), and the rewrite path did NOT (no force_json)
        self.assertIn("tools", nc.call_args.kwargs)
        self.assertFalse(nc.call_args.kwargs.get("force_json", False))
        self.assertEqual(out["report"]["files_changed"], [])


if __name__ == "__main__":
    unittest.main()
