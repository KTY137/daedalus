# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect

import daedalus.kernel.attempt_ledger as module


def _class_tree() -> ast.ClassDef:
    tree = ast.parse(inspect.getsource(module.AttemptLedger))
    node = tree.body[0]
    assert isinstance(node, ast.ClassDef)
    return node


def _method(name: str) -> ast.FunctionDef:
    node = next(
        item
        for item in _class_tree().body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return node


def test_review_requires_one_admission_and_one_canonical_schema_transaction() -> None:
    init = _method("__init__")
    enforce_calls = [
        call
        for call in ast.walk(init)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "enforce_gate0_durability"
    ]
    factory_calls = [
        call
        for call in ast.walk(init)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "open_gate0_spine_writer"
    ]
    install_calls = [
        call
        for call in ast.walk(init)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_install_single_start_invariant"
    ]
    assert len(enforce_calls) == 1
    assert len(factory_calls) == 1
    assert len(install_calls) == 1
    assert factory_calls[0].lineno <= enforce_calls[0].lineno < install_calls[0].lineno

    install = _method("_install_single_start_invariant")
    txns = [
        call
        for call in ast.walk(install)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_txn"
    ]
    connects = [
        call
        for call in ast.walk(install)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "connect"
    ]
    assert len(txns) == 1
    assert connects == []


def test_review_rejects_exception_swallowing_and_allows_cleanup_reraise() -> None:
    init = _method("__init__")
    handlers = [node for node in ast.walk(init) if isinstance(node, ast.ExceptHandler)]
    names = []
    for handler in handlers:
        assert isinstance(handler.type, ast.Name)
        names.append(handler.type.id)
    assert sorted(names) == ["BaseException", "Gate0DurabilityError"]

    admission = next(
        handler
        for handler in handlers
        if isinstance(handler.type, ast.Name)
        and handler.type.id == "Gate0DurabilityError"
    )
    admission_raises = [
        node for node in ast.walk(admission) if isinstance(node, ast.Raise)
    ]
    assert len(admission_raises) == 1
    assert admission_raises[0].cause is not None

    cleanup = next(
        handler
        for handler in handlers
        if isinstance(handler.type, ast.Name)
        and handler.type.id == "BaseException"
    )
    cleanup_raises = [
        node for node in ast.walk(cleanup) if isinstance(node, ast.Raise)
    ]
    assert len(cleanup_raises) == 1
    assert cleanup_raises[0].exc is None
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
        for node in ast.walk(cleanup)
    )


def test_review_keeps_attempt_schema_narrow_and_does_not_reconfigure_pragmas() -> None:
    source = inspect.getsource(module.AttemptLedger._install_single_start_invariant)
    assert source.count("CREATE UNIQUE INDEX IF NOT EXISTS") == 1
    assert "CREATE TABLE" not in source
    assert "ATTACH" not in source
    assert "PRAGMA" not in source
    assert "idx_attempt_lifecycle_effect_key" in source
    assert "WHERE kind = 'attempt.lifecycle'" in source


def test_review_retains_machine_readable_admission_status() -> None:
    init_source = inspect.getsource(module.AttemptLedger.__init__)
    assert "self.durability_status" in init_source
    assert "Gate0DurabilityStatus" in init_source
    assert "open_gate0_spine_writer(path)" in init_source
    assert "enforce_gate0_durability(self.spine)" in init_source
