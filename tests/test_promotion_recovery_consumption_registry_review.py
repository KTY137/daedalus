from __future__ import annotations

import ast
from pathlib import Path

import daedalus.spine as spine


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (
    ROOT / "daedalus" / "spine" / "promotion_recovery_consumption_registry.py"
)
REPORT = (
    ROOT
    / "daedalus"
    / "spine"
    / "promotion_recovery_consumption_registry_report.py"
)
PACKAGE = ROOT / "daedalus" / "spine" / "__init__.py"


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def test_installer_has_registry_authority_only() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".", 1)[0])
        elif isinstance(node, ast.Call):
            calls.append(_qualified_name(node.func))

    assert imported.isdisjoint(
        {
            "sqlite3",
            "subprocess",
            "socket",
            "urllib",
            "http",
            "shutil",
            "tempfile",
        }
    )
    forbidden_calls = {
        "begin_effect",
        "grant",
        "begin",
        "finish",
        "consume",
        "verify_promotion_recovery_decision",
        "_connect_writer",
        "promote_candidates",
    }
    assert not {name.rsplit(".", 1)[-1] for name in calls} & forbidden_calls
    assert calls.count("recognizes_recovery_consumption_method") == 1
    assert ".startswith(" not in source
    assert "MappingProxyType" in source
    assert "_refresh_captured_registry_defaults" in source


def test_scanner_hook_is_exact_and_cannot_claim_readers() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert 'SCANNER_METHODS' in source
    assert 'qualname.split(".", 1)' in source
    assert 'model.module' in source
    assert 'verify_consumption' not in source
    assert 'consumed' not in source
    assert '__daedalus_scanner_marker__' in source


def test_report_is_hard_coded_open_until_real_centralization() -> None:
    source = REPORT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert '"closed": False' in source
    assert "closed=False" in source
    assert '"constructor-performs-unguarded-schema-initialization"' in source
    assert '"consume-is-locally-owner-guarded-but-not-effect-lease-central"' in source
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "closed":
            assert isinstance(node.value, ast.Constant)
            assert node.value.value is False


def test_package_initialization_orders_both_stranglers_and_removes_aliases() -> None:
    source = PACKAGE.read_text(encoding="utf-8")
    promotion_call = "_install_promotion_execution_rows(_effect_boundary)"
    recovery_call = (
        "_install_promotion_recovery_consumption_inventory(_effect_boundary)"
    )
    assert source.count(promotion_call) == 1
    assert source.count(recovery_call) == 1
    assert source.index(promotion_call) < source.index(recovery_call)
    assert "del _install_promotion_recovery_consumption_inventory" in source
    assert "del _install_promotion_execution_rows" in source
    assert "del _effect_boundary" in source

    assert not hasattr(spine, "_install_promotion_recovery_consumption_inventory")
    assert not hasattr(spine, "_install_promotion_execution_rows")
    assert not hasattr(spine, "_effect_boundary")
