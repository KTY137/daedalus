from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daedalus.chip_design.executor import execute_argv
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

    def test_dry_run_never_requires_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_argv(["definitely-not-an-eda-tool", "--version"], cwd=tmp, dry_run=True)
            self.assertEqual(result.status, "planned")
            self.assertIsNone(result.returncode)


if __name__ == "__main__":
    unittest.main()
