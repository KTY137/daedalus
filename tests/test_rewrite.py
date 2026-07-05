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
    """Patch the module-level chat_completion to return {'content': ...}."""
    return mock.patch(
        "daedalus.providers.ollama.chat_completion",
        return_value=json.dumps({"content": content}),
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
    def test_writable_scoped_task_uses_rewrite_not_tool_loop(self):
        agent = {"name": "docs-dev", "call_name": "Lucia"}
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED), mock.patch(
            "daedalus.providers.ollama.chat_raw",
            side_effect=AssertionError("tool loop must not run for scoped writes"),
        ):
            out = OllamaProvider().run(objective="Add docstrings", repo_root=d,
                                       paths=["src/calc.py"], agent=agent, writable=True)
        self.assertEqual(out["report"]["files_changed"], ["src/calc.py"])

    def test_advisory_task_still_uses_agentic_loop(self):
        agent = {"name": "docs-dev", "call_name": "Lucia"}
        final = {"status": "needs_review", "summary": "reviewed", "files_changed": [],
                 "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        with _repo({"src/calc.py": ORIGINAL}) as d, mock.patch(
            "daedalus.providers.ollama.chat_raw",
            return_value={"content": json.dumps(final)},
        ) as chat_raw, mock.patch(
            "daedalus.providers.ollama.chat_completion",
            side_effect=AssertionError("rewrite path must not run for advisory tasks"),
        ):
            out = OllamaProvider().run(objective="Review the calc helpers", repo_root=d,
                                       paths=["src/calc.py"], agent=agent, writable=False)
        self.assertTrue(chat_raw.called)
        self.assertEqual(out["report"]["files_changed"], [])


if __name__ == "__main__":
    unittest.main()
