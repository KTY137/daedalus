# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from daedalus.chip_design.cli import main as chip_main
from daedalus.chip_design.executor import _MAX_CAPTURE_CHARS, _bounded, execute_argv
from daedalus.chip_design.sources import classify_source, discover_sources
from daedalus.chip_design.toolchains import build_rtl_lint_argv, build_tcl_argv


class SourceClassification(unittest.TestCase):
    def test_rtl_and_constraints_are_distinct(self):
        self.assertEqual(classify_source("rtl/top.sv").language, "systemverilog")
        self.assertTrue(classify_source("rtl/top.sv").synthesizable)
        self.assertEqual(classify_source("constraints/top.xdc").kind, "constraint")
        self.assertFalse(classify_source("constraints/top.xdc").synthesizable)
        self.assertEqual(classify_source("flow/build.tcl").role, "eda/automation")

    def test_scan_is_stable_and_ignores_build_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rtl").mkdir()
            (root / "rtl" / "b.sv").write_text("module b; endmodule\n")
            (root / "rtl" / "a.v").write_text("module a; endmodule\n")
            (root / "build").mkdir()
            (root / "build" / "generated.sv").write_text("module g; endmodule\n")
            self.assertEqual([s.path for s in discover_sources(root)], ["rtl/a.v", "rtl/b.sv"])

    def test_scan_max_files_is_an_exact_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.v").write_text("module a; endmodule\n")
            (root / "b.sv").write_text("module b; endmodule\n")
            self.assertEqual(discover_sources(root, max_files=0), [])
            self.assertEqual([s.path for s in discover_sources(root, max_files=1)], ["a.v"])
            with self.assertRaises(ValueError):
                discover_sources(root, max_files=-1)

    def test_missing_scan_root_is_not_an_empty_design(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            with self.assertRaises(ValueError):
                discover_sources(missing)

    def test_scan_cli_normalizes_validation_to_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                chip_main(["scan", tmp, "--max-files", "-1"])
            self.assertEqual(caught.exception.code, 2)


class TclInvocation(unittest.TestCase):
    def _repo(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "flow.tcl").write_text("puts hello\n")
        return tmp, root

    def test_vendor_argv_shapes(self):
        tmp, root = self._repo()
        try:
            self.assertEqual(
                build_tcl_argv("vivado", "flow.tcl", repo_root=root, script_args=("PART=x",)),
                ["vivado", "-mode", "batch", "-source", str(root / "flow.tcl"), "-tclargs", "PART=x"],
            )
            self.assertEqual(
                build_tcl_argv("quartus", "flow.tcl", repo_root=root, script_args=("Agilex",)),
                ["quartus_sh", "-t", str(root / "flow.tcl"), "Agilex"],
            )
            self.assertEqual(
                build_tcl_argv("yosys", "flow.tcl", repo_root=root),
                ["yosys", "-c", str(root / "flow.tcl")],
            )
            self.assertEqual(
                build_tcl_argv("openroad", "flow.tcl", repo_root=root),
                ["openroad", "-no_init", "-exit", str(root / "flow.tcl")],
            )
        finally:
            tmp.cleanup()

    def test_unknown_direct_args_are_refused_for_openroad(self):
        tmp, root = self._repo()
        try:
            with self.assertRaises(ValueError):
                build_tcl_argv("openroad", "flow.tcl", repo_root=root, script_args=("x",))
        finally:
            tmp.cleanup()

    def test_script_cannot_escape_repo(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as other:
            external = Path(other) / "flow.tcl"
            external.write_text("puts nope\n")
            with self.assertRaises(ValueError):
                build_tcl_argv("tclsh", external, repo_root=repo)

    def test_symlinked_script_cannot_escape_repo(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as other:
            external = Path(other) / "flow.tcl"
            external.write_text("puts nope\n")
            link = Path(repo) / "flow.tcl"
            try:
                link.symlink_to(external)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")
            with self.assertRaises(ValueError):
                build_tcl_argv("tclsh", link, repo_root=repo)


class RtlLint(unittest.TestCase):
    def test_verilator_command_is_lint_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc").mkdir()
            (root / "top.sv").write_text("module top; endmodule\n")
            argv = build_rtl_lint_argv(
                "verilator", ["top.sv"], repo_root=root, top="top",
                include_dirs=["inc"], defines=["SIM=1"],
            )
            self.assertEqual(argv[:3], ["verilator", "--lint-only", "-Wall"])
            self.assertIn("--top-module", argv)
            self.assertIn(f"-I{root / 'inc'}", argv)
            self.assertIn("-DSIM=1", argv)


class ExecutionReceipts(unittest.TestCase):
    def test_dry_run_never_requires_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_argv(["definitely-not-an-eda-tool", "--version"], cwd=tmp, dry_run=True)
            self.assertEqual(result.status, "planned")
            self.assertIsNone(result.returncode)

    def test_live_missing_tool_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_argv(["definitely-not-an-eda-tool-9f2ce9", "--version"], cwd=tmp, dry_run=False)
            self.assertEqual(result.status, "missing")
            self.assertIsNone(result.returncode)
            self.assertIn("not found on PATH", result.stderr)

    def test_capture_bound_includes_the_truncation_marker(self):
        text = "A" * (_MAX_CAPTURE_CHARS + 10_000) + "TAIL"
        captured, truncated = _bounded(text)
        self.assertTrue(truncated)
        self.assertEqual(len(captured), _MAX_CAPTURE_CHARS)
        self.assertIn("[Daedalus truncated EDA output]", captured)
        self.assertTrue(captured.startswith("A"))
        self.assertTrue(captured.endswith("TAIL"))

    def test_timeout_returns_a_bounded_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_argv(
                [sys.executable, "-c", "import time; time.sleep(1)"],
                cwd=tmp,
                timeout_s=0.02,
                dry_run=False,
            )
            self.assertEqual(result.status, "timeout")
            self.assertIsNone(result.returncode)


if __name__ == "__main__":
    unittest.main()
