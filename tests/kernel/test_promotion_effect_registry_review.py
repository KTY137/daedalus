from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "daedalus" / "spine" / "promotion_effect_registry.py"
PACKAGE_INIT = ROOT / "daedalus" / "spine" / "__init__.py"


def test_counter_review_installer_has_no_runtime_or_owner_authority() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(INSTALLER))
    forbidden_names = {
        "subprocess",
        "Popen",
        "system",
        "sqlite3",
        "GitWorktreeManager",
        "issue_owner_approval",
        "consume_owner_approval",
        "begin_effect",
    }
    assert not {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in forbidden_names
    }
    assert "Wiring.CENTRAL" not in source
    assert "merge_pull_request" not in source
    assert "promote_candidates(" not in source


def test_counter_review_has_one_bounded_registry_append_and_projection_refresh() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert source.count("boundary.ENTRYPOINTS = (*boundary.ENTRYPOINTS, *required)") == 1
    assert source.count("boundary.REGISTRY_BY_ID = MappingProxyType(") == 1
    assert source.count("registry_sha256.__defaults__") == 1
    assert source.count("begin_effect.__kwdefaults__") == 2
    assert source.count("check_conformance.__kwdefaults__") == 2
    assert source.count("materialize_promotion_execution_rows(") == 1
    assert source.count("promotion execution rows are partially or incorrectly installed") == 1
    assert source.count("boundary.ENTRYPOINTS[-len(required) :]") == 1
    assert source.count("promotion execution rows are not the exact ordered registry suffix") == 1


def test_counter_review_package_initializes_before_export_projection() -> None:
    source = PACKAGE_INIT.read_text(encoding="utf-8")
    install = "_install_promotion_execution_rows(_effect_boundary)"
    assert source.count(install) == 1
    assert source.index(install) < source.index("__all__ = [")
    assert "install_promotion_execution_rows" not in source[source.index("__all__ = [") :]


def test_counter_review_exact_anchor_and_identity_sets_are_source_visible() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    for entrypoint_id in (
        "kernel.promotion_execution.open",
        "kernel.promotion_execution.begin",
        "kernel.promotion_execution.complete",
    ):
        assert source.count(f'"{entrypoint_id}"') >= 2
    for anchor in (
        "open_gate0_spine_writer",
        "_install_single_start_invariant",
        "record_intent",
        "mark_completed",
    ):
        assert source.count(f'"{anchor}"') == 1
