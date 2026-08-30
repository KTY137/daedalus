# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path

MODULE = (
    Path(__file__).resolve().parents[2]
    / "daedalus"
    / "gates"
    / "fault_matrix.py"
)


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _class(name: str) -> ast.ClassDef:
    matches = [
        node
        for node in _tree().body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _method(class_name: str, method_name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in _class(class_name).body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    ]
    assert len(matches) == 1
    return matches[0]


def test_scenario_wire_checks_exact_lists_before_tuple_conversion() -> None:
    source = ast.unparse(_method("FaultScenarioSpec", "from_dict"))

    assert "array_fields = ('targeted_invariants', 'expected_durable_markers', 'forbidden_durable_markers')" in source
    assert "type(payload[field]) is not list" in source
    assert "fault scenario arrays must be exact lists" in source
    assert source.index("type(payload[field]) is not list") < source.index(
        "targeted_invariants=tuple(payload['targeted_invariants'])"
    )


def test_verification_wire_rejects_python_bool_int_aliasing() -> None:
    source = ast.unparse(
        _method("FaultMatrixVerificationReceipt", "from_dict")
    )

    assert "type(payload[field]) is not bool" in source
    assert "fault matrix verification claims must be exact bools" in source
    assert "type(payload['failure_count']) is not int" in source
    assert "fault matrix verification failure_count must be exact int" in source
    assert source.index("type(payload[field]) is not bool") < source.index(
        "result = cls"
    )
    assert source.index("type(payload['failure_count']) is not int") < source.index(
        "result = cls"
    )
