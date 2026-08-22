from __future__ import annotations

import ast
import inspect

import daedalus.gates.report_v3 as report_v3


def test_v3_is_additive_and_does_not_replace_v2_import_path() -> None:
    source = inspect.getsource(report_v3)
    assert "from .report import GateReport, build_gate0_report" in source
    assert "class GateReportV3(GateReport)" in source
    assert "daedalus-gate-report/4" in source
    assert "GateReport =" not in source


def test_v3_closure_mechanically_requires_repository_write_evidence() -> None:
    blockers = inspect.getsource(report_v3.GateReportV3.blockers.fget)
    assert "repository_write_inventory_sha256:missing" in blockers
    assert "repository_write_scan_input_sha256:missing" in blockers
    assert "repository_write_files_scanned:missing" in blockers
    assert "repository_write_inventory_generation:unsupported:" in blockers
    assert "repository_write_failures:" in blockers
    closed = inspect.getsource(report_v3.GateReportV3.closed.fget)
    assert "not self.blockers" in closed


def test_builder_uses_canonical_v2_scanner_and_never_accepts_caller_failures() -> None:
    signature = inspect.signature(report_v3.build_gate0_report_v3)
    assert "repository_write_failures" not in signature.parameters
    assert "repository_write_inventory_sha256" not in signature.parameters
    source = inspect.getsource(report_v3.build_gate0_report_v3)
    base_helper = inspect.getsource(report_v3._build_base_report)
    inventory_helper = inspect.getsource(report_v3._repository_write_evidence)
    assert source.count("_build_base_report(") == 2
    assert source.count("_repository_write_evidence(") == 2
    assert "build_gate0_report(" in base_helper
    assert "type(report) is not GateReport" in base_helper
    assert "scan_repository_write_surfaces_v2(" in inventory_helper
    assert "inventory.digest" in inventory_helper
    assert "inventory.scan_input_sha256" in inventory_helper
    assert "inventory.files_scanned" in inventory_helper
    assert "for surface in inventory.blockers" in inventory_helper
    assert '"inventory-refused"' in inventory_helper


def test_builder_snapshots_inputs_and_refuses_observed_composition_drift() -> None:
    source = inspect.getsource(report_v3.build_gate0_report_v3)
    assert "receipt_rows = tuple(runtime_receipts)" in source
    assert "mutation_rows = tuple(primary_checkout_mutations)" in source
    assert "dict(fault_results)" in source
    assert "base_before.to_dict() != base_after.to_dict()" in source
    assert "inventory_before != inventory_after" in source
    assert "base GateReport-v2 changed while composing GateReport-v3" in source
    assert "repository-write inventory changed while composing GateReport-v3" in source


def test_v3_parser_rejects_v2_and_requires_exact_fields() -> None:
    source = inspect.getsource(report_v3.GateReportV3.from_dict)
    assert "set(payload) != _V3_FIELDS" in source
    assert "unsupported GateReport-v3 schema" in source
    assert "GateReport-v3 digest mismatch" in source
    assert "payload is not canonical JSON data" in source
    assert "dict(payload) != report.to_dict()" in source
    assert "GateReport.from_dict" not in source


def test_v3_module_has_no_release_promotion_or_execution_authority() -> None:
    source = inspect.getsource(report_v3)
    tree = ast.parse(source)
    imported: set[str] = set()
    called_names: set[str] = set()
    called_attrs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_attrs.add(node.func.attr)
    assert imported.isdisjoint(
        {"subprocess", "socket", "requests", "httpx", "urllib", "sqlite3"}
    )
    # Write authority is exercised through methods on a path object.
    assert {"write_text", "write_bytes", "mkdir", "unlink", "replace"}.isdisjoint(
        called_attrs
    )
    # Execution authority is the bare builtin; `re.compile` is an attribute on a
    # module and is not code execution.
    assert {"exec", "eval", "compile"}.isdisjoint(called_names)
    assert {"system", "popen", "spawn", "fork", "execv"}.isdisjoint(called_attrs)
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "Gate0ReleaseReceipt" not in source
    assert "begin_effect" not in source


def test_monotonic_comparison_requires_exact_v3_subjects() -> None:
    source = inspect.getsource(report_v3.assert_monotonic_v3)
    assert "type(current) is not GateReportV3" in source
    assert "type(baseline) is not GateReportV3" in source
    assert "set(current.blockers) - set(baseline.blockers)" in source
