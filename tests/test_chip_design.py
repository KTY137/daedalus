from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from daedalus.chip_design.cli import main as chip_main
from daedalus.chip_design.executor import _MAX_CAPTURE_CHARS, _bounded, execute_argv
from daedalus.chip_design.sources import classify_source, discover_sources
from daedalus.chip_design.toolchains import (
    build_rtl_lint_argv,
    build_tcl_argv,
    interpret_version_probe,
    tool_status,
)


class SourceClassification(unittest.TestCase):
    def test_rtl_and_constraints_are_distinct(self):
        self.assertEqual(classify_source("rtl/top.sv").language, "systemverilog")
        self.assertTrue(classify_source("rtl/top.sv").synthesizable)
        self.assertEqual(classify_source("constraints/top.xdc").kind, "constraint")
        self.assertFalse(classify_source("constraints/top.xdc").synthesizable)
        self.assertEqual(classify_source("flow/build.tcl").role, "eda/automation")
        self.assertEqual(classify_source("project/design.xpr").kind, "project")
        self.assertEqual(classify_source("src/system.bd").kind, "block_design")
        self.assertEqual(classify_source("ip/uart.xci").kind, "ip_config")

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
                ["vivado", "-mode", "batch", "-source", str((root / "flow.tcl").resolve()), "-tclargs", "PART=x"],
            )
            self.assertEqual(
                build_tcl_argv("quartus", "flow.tcl", repo_root=root, script_args=("Agilex",)),
                ["quartus_sh", "-t", str((root / "flow.tcl").resolve()), "Agilex"],
            )
            self.assertEqual(
                build_tcl_argv("yosys", "flow.tcl", repo_root=root),
                ["yosys", "-c", str((root / "flow.tcl").resolve())],
            )
            self.assertEqual(
                build_tcl_argv("openroad", "flow.tcl", repo_root=root),
                ["openroad", "-no_init", "-exit", str((root / "flow.tcl").resolve())],
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
            self.assertIn(f"-I{(root / 'inc').resolve()}", argv)
            self.assertIn("-DSIM=1", argv)


class ToolDiscovery(unittest.TestCase):
    def test_status_is_read_only_and_separates_discovery_from_probe(self):
        with patch(
            "daedalus.chip_design.toolchains.find_tool_path",
            return_value=r"C:\\Xilinx\\2025.1\\Vivado\\bin\\vivado.bat",
        ):
            row = tool_status("vivado")
        self.assertTrue(row["available"])
        self.assertEqual(row["probe_status"], "not_run")
        self.assertIsNone(row["version_probe_returncode"])

    def test_vivado_nonzero_launcher_with_valid_banner_is_available_with_warning(self):
        row = interpret_version_probe(
            "vivado",
            returncode=1,
            stdout="Vivado v2025.1.1 (64-bit)\nSW Build 6140274",
        )
        self.assertEqual(row["probe_status"], "warning")
        self.assertEqual(row["version"], "2025.1.1")
        self.assertEqual(row["version_probe_returncode"], 1)
        self.assertIn("exited 1", row["probe_warning"])

    def test_unparseable_nonzero_probe_remains_failed(self):
        row = interpret_version_probe("vivado", returncode=1, stderr="launcher failed")
        self.assertEqual(row["probe_status"], "failed")
        self.assertEqual(row["version"], "")


class ExecutionReceipts(unittest.TestCase):
    def test_dry_run_never_requires_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_argv(["definitely-not-an-eda-tool", "--version"], cwd=tmp, dry_run=True)
            self.assertEqual(result.status, "planned")
            self.assertIsNone(result.returncode)

    def test_live_missing_tool_cannot_bypass_canonical_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(Exception, "NonRuntimeEffectAuthorization"):
                execute_argv(
                    ["definitely-not-an-eda-tool-9f2ce9", "--version"],
                    cwd=tmp,
                    dry_run=False,
                )

    def test_capture_bound_includes_the_truncation_marker(self):
        text = "A" * (_MAX_CAPTURE_CHARS + 10_000) + "TAIL"
        captured, truncated = _bounded(text)
        self.assertTrue(truncated)
        self.assertEqual(len(captured), _MAX_CAPTURE_CHARS)
        self.assertIn("[Daedalus truncated EDA output]", captured)
        self.assertTrue(captured.startswith("A"))
        self.assertTrue(captured.endswith("TAIL"))

    def test_timeout_knob_does_not_open_an_unadmitted_live_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(Exception, "NonRuntimeEffectAuthorization"):
                execute_argv(
                    [sys.executable, "-c", "import time; time.sleep(1)"],
                    cwd=tmp,
                    timeout_s=0.02,
                    dry_run=False,
                )


class CliLiveComposition(unittest.TestCase):
    def test_raw_live_is_retired_in_favour_of_the_project_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "top.sv"
            source.write_text("module top; endmodule\n", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                chip_main(
                    [
                        "lint",
                        str(source),
                        "--repo-root",
                        str(root),
                        "--live",
                    ]
                )
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("live execution is disabled", stderr.getvalue())
            self.assertIn("daedalus-chip run", stderr.getvalue())

    def test_raw_live_refuses_even_when_legacy_authority_flags_are_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authority = root / "authority"
            project = root / "project"
            workspace = root / "workspace"
            authority.mkdir()
            project.mkdir()
            workspace.mkdir()
            source = workspace / "top.sv"
            source.write_text("module top; endmodule\n", encoding="utf-8")
            stderr = io.StringIO()
            with patch(
                "daedalus.chip_design.cli.acquire_chip_eda_lease",
                side_effect=AssertionError("raw live reached admission"),
            ), patch(
                "daedalus.chip_design.cli.run_admitted_eda",
                side_effect=AssertionError("raw live reached execution"),
            ), redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                chip_main(
                    [
                        "lint",
                        str(source),
                        "--repo-root",
                        str(workspace),
                        "--live",
                        "--authority-root",
                        str(authority),
                        "--project-root",
                        str(project),
                        "--source-revision",
                        "a" * 40,
                        "--writable-path",
                        ".",
                    ]
                )
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("daedalus-chip run", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
