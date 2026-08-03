"""Tests for the full-file-rewrite write path (OllamaProvider._run_rewrite).

The live benchmark showed 7B models never emit write_file tool calls; the
rewrite path is the fix. Everything here is offline: the model call is mocked.
"""

import json
import os
import subprocess
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


def _make_directory_link(link: Path, target: Path) -> bool:
    """Create a real directory symlink, or a Windows junction as fallback."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        if os.name != "nt":
            return False
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True, check=False,
    )
    return completed.returncode == 0


class RewriteApplyTests(unittest.TestCase):
    def test_rewrite_applies_and_reports(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED):
            p = OllamaProvider()
            report = p._run_rewrite(
                "Add docstrings", d, ["src/calc.py"], None, 60, None,
                allowed_write_paths=["src/calc.py"])
            self.assertEqual(report["files_changed"], ["src/calc.py"])
            self.assertEqual(report["status"], "done")
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), EDITED)

    def test_identical_content_is_a_noop(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(ORIGINAL):
            report = OllamaProvider()._run_rewrite(
                "Add docstrings", d, ["src/calc.py"], None, 60, None,
                allowed_write_paths=["src/calc.py"])
        self.assertEqual(report["files_changed"], [])
        self.assertEqual(report["status"], "needs_review")
        self.assertIn("no change produced", report["summary"])

    def test_truncation_guard_refuses_short_result(self):
        long_src = ORIGINAL * 20
        with _repo({"src/calc.py": long_src}) as d, _model_returns("def add(a, b):\n"):
            report = OllamaProvider()._run_rewrite(
                "Refactor", d, ["src/calc.py"], None, 60, None,
                allowed_write_paths=["src/calc.py"])
            self.assertEqual(report["files_changed"], [])
            self.assertIn("suspected truncation", report["summary"])
            # original untouched
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), long_src)

    def test_elision_marker_is_rejected(self):
        elided = ORIGINAL + "\n# ... rest of the file unchanged\n"
        with _repo({"src/calc.py": ORIGINAL * 3}) as d, _model_returns(elided):
            report = OllamaProvider()._run_rewrite(
                "Refactor", d, ["src/calc.py"], None, 60, None,
                allowed_write_paths=["src/calc.py"])
            self.assertEqual(report["files_changed"], [])
            self.assertIn("elision marker", report["summary"])
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), ORIGINAL * 3)

    def test_preexisting_marker_text_is_not_a_false_positive(self):
        # the file already says "remains unchanged" -- keeping it must not reject
        src = ORIGINAL + "# behavior remains unchanged since v1\n"
        edited = 'def add(a, b):\n    """Add."""\n    return a + b\n# behavior remains unchanged since v1\n'
        with _repo({"src/calc.py": src}) as d, _model_returns(edited):
            report = OllamaProvider()._run_rewrite(
                "Add docstring", d, ["src/calc.py"], None, 60, None,
                allowed_write_paths=["src/calc.py"])
            self.assertEqual(report["files_changed"], ["src/calc.py"])

    def test_protected_path_is_skipped(self):
        # default policy always denies secret-ish paths
        with _repo({"secret_keys.py": ORIGINAL}) as d, _model_returns(EDITED):
            report = OllamaProvider()._run_rewrite(
                "Edit", d, ["secret_keys.py"], None, 60, None,
                allowed_write_paths=["secret_keys.py"])
            self.assertEqual(report["files_changed"], [])
            self.assertIn("protected path", report["summary"])
            self.assertEqual((Path(d) / "secret_keys.py").read_text(encoding="utf-8"), ORIGINAL)

    def test_path_escape_is_skipped(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED):
            report = OllamaProvider()._run_rewrite(
                "Edit", d, ["../outside.py"], None, 60, None,
                allowed_write_paths=["../outside.py"])
        self.assertEqual(report["files_changed"], [])
        self.assertIn("path traversal", report["summary"])

    def test_rollback_restores_original(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED):
            p = OllamaProvider()
            report = p._run_rewrite(
                "Add docstrings", d, ["src/calc.py"], None, 60, None,
                allowed_write_paths=["src/calc.py"])
            self.assertEqual(report["files_changed"], ["src/calc.py"])
            restored = p.rollback()
            self.assertEqual(restored, [str((Path(d) / "src/calc.py").resolve())])
            self.assertEqual((Path(d) / "src/calc.py").read_text(encoding="utf-8"), ORIGINAL)


class WriteScopeTests(unittest.TestCase):
    def test_dispatch_changes_only_the_exact_component_target(self):
        """The tool path performs a real disk write, while prefix and traversal
        aliases are refused and remain byte-identical."""
        with _repo({"src/calc.py": ORIGINAL, "src/calc.py.bak": ORIGINAL}) as d:
            provider = OllamaProvider()
            changed: list[str] = []
            denied_before = (Path(d) / "src/calc.py.bak").read_bytes()

            prefix = provider._dispatch(
                "write_file", {"path": "src/calc.py.bak", "content": EDITED},
                d, None, changed, True, ["src/calc.py"])
            traversal = provider._dispatch(
                "write_file", {"path": "src/../src/calc.py", "content": EDITED},
                d, None, changed, True, ["src/calc.py"])
            written = provider._dispatch(
                "write_file", {"path": "src\\calc.py", "content": EDITED},
                d, None, changed, True, ["src/calc.py"])

            self.assertIn("not exactly declared", prefix)
            self.assertIn("path traversal", traversal)
            self.assertEqual(written, "OK: wrote src/calc.py.")
            self.assertEqual(changed, ["src/calc.py"])
            self.assertEqual((Path(d) / "src/calc.py").read_text("utf-8"), EDITED)
            self.assertEqual((Path(d) / "src/calc.py.bak").read_bytes(), denied_before)

    def test_dispatch_and_rewrite_refuse_real_link_escape_without_touching_target(self):
        """Both physical write sites reject the same real symlink/junction
        component even when its lexical path is explicitly declared."""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            repo = base / "repo"
            outside = base / "outside"
            repo.mkdir()
            outside.mkdir()
            victim = outside / "victim.py"
            victim.write_bytes(ORIGINAL.encode("utf-8"))
            link = repo / "linked"
            if not _make_directory_link(link, outside):
                self.skipTest("directory symlink/junction unavailable on this host")
            before = victim.read_bytes()
            provider = OllamaProvider()
            try:
                with _model_returns(EDITED) as model_call:
                    report = provider._run_rewrite(
                        "Edit", str(repo), ["linked/victim.py"], None, 60, None,
                        allowed_write_paths=["linked/victim.py"])
                dispatch = provider._dispatch(
                    "write_file", {"path": "linked/victim.py", "content": EDITED},
                    str(repo), None, [], True, ["linked/victim.py"])

                model_call.assert_not_called()
                self.assertEqual(report["files_changed"], [])
                self.assertIn("symlink or reparse", report["summary"])
                self.assertIn("symlink or reparse", dispatch)
                self.assertEqual(victim.read_bytes(), before)
            finally:
                # Remove the link itself before TemporaryDirectory cleanup; do
                # not ask a recursive remover to interpret a Windows junction.
                try:
                    if link.is_symlink():
                        link.unlink()
                    elif link.exists():
                        link.rmdir()
                except OSError:
                    pass

    def test_public_write_mode_without_scope_fails_before_model_or_disk(self):
        agent = {"name": "docs-dev", "call_name": "Lucia"}
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED) as model_call:
            before = (Path(d) / "src/calc.py").read_bytes()
            out = OllamaProvider().run(
                objective="Add docstrings", repo_root=d, paths=["src/calc.py"],
                agent=agent, writable=True)

            model_call.assert_not_called()
            self.assertEqual(out["report"]["status"], "blocked")
            self.assertIn("allowed_write_paths", out["report"]["summary"])
            self.assertEqual(out["wrote"], [])
            self.assertFalse(out["did_work"])
            self.assertEqual((Path(d) / "src/calc.py").read_bytes(), before)

    def test_public_write_mode_with_only_invalid_scope_fails_before_model(self):
        with _repo({"src/calc.py": ORIGINAL}) as d, _model_returns(EDITED) as model_call:
            before = (Path(d) / "src" / "calc.py").read_bytes()
            out = OllamaProvider().run(
                objective="change", repo_root=d, paths=["src/calc.py"],
                agent={"name": "coder"}, writable=True,
                allowed_write_paths=["../outside.py", "src/file.py:stream"],
            )
            model_call.assert_not_called()
            self.assertEqual((Path(d) / "src" / "calc.py").read_bytes(), before)
            self.assertEqual(out["wrote"], [])
            self.assertIn("allowed_write_paths", out["report"]["summary"])

    def test_portable_windows_aliases_never_match_the_write_scope(self):
        provider = OllamaProvider()
        with _repo({"src/calc.py": ORIGINAL}) as d:
            for rel in ("src/calc.py:stream", "src/CON", "src/calc.py.", "src/calc.py "):
                result = provider._dispatch(
                    "write_file", {"path": rel, "content": EDITED}, d, None,
                    [], True, [rel],
                )
                self.assertIn("portable exact filename", result)
            self.assertEqual((Path(d) / "src" / "calc.py").read_text(encoding="utf-8"), ORIGINAL)


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
                                       paths=["src/calc.py"], agent=agent, writable=True,
                                       allowed_write_paths=["src/calc.py"])
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
