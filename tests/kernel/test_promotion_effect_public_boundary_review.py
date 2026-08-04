from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.kairos.promotion_effect_public_boundary as boundary


SOURCE_PATH = Path(boundary.__file__).resolve()
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected one {name}, found {len(matches)}"
    return matches[0]


def _calls(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            parts = [target.attr]
            value = target.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            names.append(".".join(reversed(parts)))
    return names


def test_module_is_inert_and_has_no_repository_effect_authority():
    forbidden_import_roots = {
        "subprocess",
        "sqlite3",
        "socket",
        "urllib",
        "http",
        "shutil",
        "tempfile",
    }
    imports: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert imports.isdisjoint(forbidden_import_roots)
    assert "GitWorktreeManager" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionExecutionLedger" not in SOURCE
    assert "merge_pull_request" not in SOURCE
    assert "update_ref" not in SOURCE
    assert "os.system" not in SOURCE
    assert "Popen" not in SOURCE

    top_level_calls = [
        node
        for node in TREE.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert top_level_calls == []


def test_public_installer_resolves_only_the_canonical_lifecycle_module():
    installer = _function("install_promotion_effect_public_boundary")
    calls = _calls(installer)
    assert calls.count("_install_boundary") == 1
    assert all(
        forbidden not in calls
        for forbidden in (
            "grant",
            "begin",
            "finish",
            "promote_candidates",
            "record_intent",
            "mark_completed",
        )
    )
    relative_imports = [
        node
        for node in ast.walk(installer)
        if isinstance(node, ast.ImportFrom)
    ]
    assert len(relative_imports) == 1
    assert relative_imports[0].level == 1
    assert relative_imports[0].module is None
    assert [alias.name for alias in relative_imports[0].names] == [
        "promotion_effect_lifecycle"
    ]


def test_outer_facade_requires_capability_before_scope_entry():
    installer = _function("_install_boundary")
    public = next(
        node
        for node in installer.body
        if isinstance(node, ast.FunctionDef) and node.name == "public_entrypoint"
    )
    statements = public.body
    missing_guard_index = next(
        index
        for index, node in enumerate(statements)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Constant)
        and node.test.left.value == "promotion_effect_capability"
    )
    pop_index = next(
        index
        for index, node in enumerate(statements)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "pop"
            for child in ast.walk(node)
        )
    )
    scope_index = next(
        index
        for index, node in enumerate(statements)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "set"
            for child in ast.walk(node)
        )
    )
    assert missing_guard_index < pop_index < scope_index
    assert _calls(public).count("lifecycle_entry") == 1
    assert any(
        isinstance(node, ast.Try) and node.finalbody
        for node in ast.walk(public)
    )


def test_scoped_delegate_has_one_guarded_delegate_call():
    installer = _function("_install_boundary")
    facade = next(
        node
        for node in installer.body
        if isinstance(node, ast.ClassDef) and node.name == "_ScopedDelegateFacade"
    )
    method = next(
        node
        for node in facade.body
        if isinstance(node, ast.FunctionDef) and node.name == "promote_candidates"
    )
    calls = _calls(method)
    assert calls.count("call_scope.get") == 1
    assert calls.count("delegate") == 1
    delegate_call = next(
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "delegate"
    )
    guard = next(node for node in method.body if isinstance(node, ast.If))
    assert guard.lineno < delegate_call.lineno


def test_compatibility_metadata_does_not_publish_delegate_alias():
    copier = _function("_copy_compatibility_metadata")
    assert "__wrapped__" not in inspect.getsource(boundary._copy_compatibility_metadata)
    assert "functools" not in SOURCE
    assert "wraps" not in SOURCE
    assert _calls(copier).count("inspect.signature") == 1


def test_public_exports_do_not_include_private_installation_authority():
    assert boundary.__all__ == (
        "PromotionEffectPublicBoundaryError",
        "PromotionEffectPublicBoundaryReceipt",
        "install_promotion_effect_public_boundary",
    )
    assert "_install_boundary" not in boundary.__all__
    assert "_InstalledBoundary" not in boundary.__all__
