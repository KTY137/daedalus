from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "effect_ledger_contention_fault_executor.py"


def _source_and_tree():
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(EXECUTOR_PATH))


def test_fixture_has_no_provider_or_process_effect_boundary() -> None:
    source, tree = _source_and_tree()
    forbidden = {
        ("subprocess", "Popen"),
        ("subprocess", "run"),
        ("os", "system"),
        ("os", "popen"),
    }
    observed: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            observed.add((node.func.value.id, node.func.attr))
        for keyword in node.keywords:
            assert not (
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            )
    assert not (observed & forbidden)
    assert "ledger.begin(" in source
    assert "provider_called = True" in source
    assert "execution_count == 0" in source


def test_bounded_ledger_changes_only_connection_timeout() -> None:
    source, tree = _source_and_tree()
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    bounded = classes["BoundedEffectLeaseLedger"]
    methods = {
        node.name
        for node in bounded.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {"__init__", "_connect"}
    assert "super().__init__(path)" in source
    assert "PRAGMA busy_timeout" in source
    assert "BEGIN IMMEDIATE" in source


def test_raw_evidence_excludes_sqlite_message_and_plain_database_path() -> None:
    source, _ = _source_and_tree()
    assert '"database_path_sha256"' in source
    assert '"database_path"' not in source
    assert '"exception_module"' in source
    assert '"exception_type"' in source
    assert '"sqlite_errorcode"' in source
    assert '"exception_message"' not in source
    assert "str(exc).lower()" in source


def test_candidate_cannot_claim_trust_attestation_or_gate_closure() -> None:
    _, tree = _source_and_tree()
    forbidden_true = {"trusted", "attested", "gate_closure_claimed"}
    observed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and key.value in forbidden_true:
                observed.add(key.value)
                assert isinstance(value, ast.Constant)
                assert value.value is False
    assert observed == forbidden_true


def test_only_sqlite_operational_error_is_classified_as_expected_fault() -> None:
    source, tree = _source_and_tree()
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    operational_handlers = [
        node
        for node in handlers
        if isinstance(node.type, ast.Attribute)
        and isinstance(node.type.value, ast.Name)
        and node.type.value.id == "sqlite3"
        and node.type.attr == "OperationalError"
    ]
    assert len(operational_handlers) == 1
    assert "except BaseException" not in source
    assert "except Exception as exc" not in source
