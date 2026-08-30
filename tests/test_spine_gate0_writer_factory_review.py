# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect

import daedalus.spine as spine
import daedalus.spine.durability as durability
from daedalus.spine.ledger import SpineLedger


def test_review_factory_is_public_but_private_profile_class_is_not() -> None:
    assert spine.open_gate0_spine_writer is durability.open_gate0_spine_writer
    assert "open_gate0_spine_writer" in spine.__all__
    assert "_Gate0OpeningSpineLedger" not in spine.__all__
    assert "_Gate0OpeningSpineLedger" not in durability.__all__


def test_review_opening_profile_changes_only_synchronous_mode() -> None:
    subclass = durability._Gate0OpeningSpineLedger
    assert subclass.__bases__ == (SpineLedger,)
    methods = {
        name
        for name, value in subclass.__dict__.items()
        if callable(value) and not name.startswith("__")
    }
    assert methods == {"_apply_pragmas"}
    source = inspect.getsource(subclass._apply_pragmas)
    assert "super()._apply_pragmas()" in source
    assert source.count("PRAGMA synchronous=FULL") == 1
    for forbidden in (
        "CREATE TABLE",
        "CREATE INDEX",
        "INSERT",
        "UPDATE",
        "DELETE",
        "ATTACH",
        "journal_mode",
    ):
        assert forbidden not in source


def test_review_factory_readback_precedes_return_and_failure_closes() -> None:
    source = inspect.getsource(durability.open_gate0_spine_writer)
    tree = ast.parse(source)
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    inspect_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "inspect_gate0_durability"
    ]
    returns = [node.lineno for node in ast.walk(function) if isinstance(node, ast.Return)]
    close_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
    ]
    assert len(inspect_lines) == 1
    assert len(returns) == 1
    assert inspect_lines[0] < returns[0]
    assert len(close_calls) == 2
    assert "if not status.satisfied" in source


def test_review_factory_has_no_read_only_or_legacy_normal_escape_hatch() -> None:
    source = inspect.getsource(durability.open_gate0_spine_writer)
    assert "read_only=False" in source
    assert "synchronous=NORMAL" not in source
    assert "SpineLedger(" not in source.replace("_Gate0OpeningSpineLedger(", "")
    assert "max(DEFAULT_BUSY_TIMEOUT_MS" in source
