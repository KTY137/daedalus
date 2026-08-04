from __future__ import annotations

import ast
import inspect

import daedalus.spine.promotion_recovery_consumption_effect_rows as rows


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def test_descriptor_module_has_no_registry_or_effect_authority() -> None:
    source = inspect.getsource(rows)
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := _qualified_name(node.func)) is not None
    }

    assert "daedalus.spine.effect_boundary" not in imports
    assert "effect_boundary" not in imports
    assert not {
        "begin_effect",
        "verify_promotion_recovery_decision",
        "sqlite3.connect",
        "subprocess.run",
        "subprocess.Popen",
        "PromotionRecoveryConsumptionLedger",
    } & calls
    assert "ENTRYPOINTS" not in vars(rows)
    assert "REGISTRY_BY_ID" not in vars(rows)
    assert "GUARD_CONTRACT_IMPLEMENTED" not in vars(rows)


def test_descriptor_module_cannot_mutate_an_injected_registry() -> None:
    source = inspect.getsource(
        rows.materialize_promotion_recovery_consumption_rows
    )
    tree = ast.parse(source)

    assert "registry" not in inspect.signature(
        rows.materialize_promotion_recovery_consumption_rows
    ).parameters
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"append", "extend", "update", "add"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {
            "entrypoints",
            "registry",
            "registry_by_id",
            "guard_contracts",
        }
        for node in ast.walk(tree)
    )


def test_exact_two_row_table_is_literal_and_noncentral() -> None:
    descriptors = rows.PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS

    assert len(descriptors) == 2
    assert tuple(row.entrypoint_id for row in descriptors) == (
        "kernel.promotion_recovery_consumption.open",
        "kernel.promotion_recovery_consumption.consume",
    )
    assert all(row.effects == ("filesystem_write",) for row in descriptors)
    assert all(row.wiring == "local_guards" for row in descriptors)
    assert all(row.anchors for row in descriptors)
    assert "central" not in {row.wiring for row in descriptors}


def test_descriptor_identity_target_guard_and_anchor_checks_run_at_import() -> None:
    source = inspect.getsource(rows)
    module_tree = ast.parse(source)
    import_checks = [
        node
        for node in module_tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and _qualified_name(node.value.func) == "_assert_exact_descriptors"
    ]

    assert len(import_checks) == 1
    assert "expected_target" in source
    assert "expected_guards" in source
    assert "descriptor anchors are duplicated" in source


def test_materializer_has_no_kwargs_or_default_canonical_authority() -> None:
    signature = inspect.signature(
        rows.materialize_promotion_recovery_consumption_rows
    )

    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    for name in (
        "entrypoint_spec",
        "guard_anchor",
        "surface_values",
        "effect_values",
        "wiring_values",
    ):
        assert signature.parameters[name].default is inspect.Parameter.empty


def test_materializer_preserves_exact_guards_and_anchors() -> None:
    source = inspect.getsource(
        rows.materialize_promotion_recovery_consumption_rows
    )

    assert "guard_contracts=descriptor.guard_contracts" in source
    assert "guard_anchor(target=target, call=call)" in source
    assert "anchors=anchors" in source
    assert "effects=effects" in source
    assert "wiring=wiring" in source
