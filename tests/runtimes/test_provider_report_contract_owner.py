"""Compatibility and direction checks for the provider report contract owner."""

from __future__ import annotations

import ast
import pickle
from pathlib import Path

import daedalus
import daedalus.schemas as schemas
from daedalus.orchestration import legacy_reports
from daedalus.runtimes import contracts
from daedalus.runtimes.contracts import provider_report
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "daedalus" / "runtimes" / "contracts" / "provider_report.py"
LEGACY = ROOT / "daedalus" / "orchestration" / "legacy_reports.py"


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_all_public_paths_resolve_to_exact_runtime_objects() -> None:
    assert schemas.AgentReport is provider_report.AgentReport
    assert schemas.REPORT_KEYS is provider_report.REPORT_KEYS
    assert schemas.validate_report is provider_report.validate_report
    assert legacy_reports.AgentReport is provider_report.AgentReport
    assert legacy_reports.REPORT_KEYS is provider_report.REPORT_KEYS
    assert legacy_reports.validate_report is provider_report.validate_report
    assert contracts.AgentReport is provider_report.AgentReport
    assert contracts.REPORT_KEYS is provider_report.REPORT_KEYS
    assert contracts.validate_report is provider_report.validate_report
    assert daedalus.AgentReport is provider_report.AgentReport
    assert daedalus.validate_report is provider_report.validate_report


def test_orchestration_module_retains_only_its_own_record_implementations() -> None:
    definitions = _top_level_definitions(LEGACY)
    assert "AgentTask" in definitions
    assert "RunState" in definitions
    assert "AgentReport" not in definitions
    assert "validate_report" not in definitions


def test_runtime_owner_has_no_outer_layer_imports() -> None:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        name.startswith(
            (
                "daedalus.orchestration",
                "daedalus.interfaces",
                "daedalus.gates",
                "daedalus.providers",
                "daedalus.chip_design",
            )
        )
        for name in imports
    )


def test_report_validation_wire_behavior_is_unchanged() -> None:
    valid = provider_report.AgentReport(
        status="done",
        summary="contract owner",
        files_changed=["src/example.py"],
        tests_run=["pytest"],
        handoff={"next": "review"},
    ).to_dict()
    assert provider_report.validate_report(valid) == []
    assert provider_report.validate_report({**valid, "summary": ""}) == [
        "summary must be a non-empty string no longer than 600 characters"
    ]


def test_old_pickle_globals_resolve_to_runtime_owner() -> None:
    for module in ("daedalus.schemas", "daedalus.orchestration.legacy_reports"):
        old_global = f"c{module}\nAgentReport\n.".encode("ascii")
        assert pickle.loads(old_global) is provider_report.AgentReport


def test_structure_packet_keeps_effect_registry_exact() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
