# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "daedalus" / "kernel" / "promotion_execution.py"
READER = ROOT / "daedalus" / "kernel" / "promotion_execution_reader.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing {name}")


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"missing {class_name}.{method_name}")


def _segment(path: Path, node: ast.AST) -> str:
    value = ast.get_source_segment(_source(path), node)
    assert value is not None
    return value


def _calls(path: Path) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(_tree(path)):
        if not isinstance(item, ast.Call):
            continue
        current = item.func
        parts: list[str] = []
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            names.add(".".join(reversed(parts)))
    return names


def test_main_ledger_never_uses_permissive_security_row_hydration() -> None:
    source = _source(MAIN)
    assert "read_promotion_execution_intents" in source
    assert "PromotionExecutionReadError" in source
    assert "resolve_by_effect" not in source
    assert ".open_intents(" not in source
    reader = _method(MAIN, "PromotionExecutionLedger", "_read_intents")
    segment = _segment(MAIN, reader)
    assert "read_promotion_execution_intents(" in segment
    assert "strict promotion execution Event-Store projection refused" in segment


def test_raw_reader_is_read_only_and_rejects_ambiguous_json() -> None:
    source = _source(READER)
    assert "mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    strict = _segment(READER, _function(READER, "_strict_json"))
    assert "object_pairs_hook=_reject_duplicate_pairs" in strict
    assert "parse_constant=_reject_constant" in strict
    assert "rendered != raw" in strict
    assert 'encode("ascii", "strict")' in strict
    assert "_MAX_JSON_BYTES = 4 * 1024 * 1024" in source


def test_raw_reader_rechecks_payload_digest_and_event_sequence() -> None:
    reader = _function(READER, "read_promotion_execution_intents")
    segment = _segment(READER, reader)
    for required in (
        "expected_payload_sha",
        "payload digest is invalid",
        "len(events) > 2",
        "STATE_INTENDED",
        "start detail does not bind payload",
        "completed promotion execution detail has wrong shape",
        "failed promotion execution detail has wrong shape",
        "unknown promotion execution event state",
    ):
        assert required in segment


def test_raw_reader_has_no_write_authority() -> None:
    source = _source(READER).upper()
    for statement in (
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "CREATE TABLE",
        "DROP TABLE",
        "ALTER TABLE",
        "REPLACE INTO",
    ):
        assert statement not in source
    calls = _calls(READER)
    assert "Path.write_text" not in calls
    assert "Path.write_bytes" not in calls


def test_raw_projection_adds_no_git_owner_or_promotion_authority() -> None:
    source = (_source(MAIN) + _source(READER)).lower()
    assert "issue_owner_approval" not in source
    assert "promote_candidates(" not in source
    assert "merge_pull_request" not in source
    assert "subprocess.run" not in source
    assert "path.write_text" not in source
    assert "path.write_bytes" not in source
