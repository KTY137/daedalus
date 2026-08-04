from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "daedalus" / "kernel" / "promotion_execution.py"
READER = ROOT / "daedalus" / "kernel" / "promotion_execution_reader.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(_source(path), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing {name}")


def _segment(path: Path, node: ast.AST) -> str:
    value = ast.get_source_segment(_source(path), node)
    assert value is not None
    return value


def test_writer_requests_a_unique_partial_effect_key_index() -> None:
    source = _source(WRITER)
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in source
    assert "idx_promotion_execution_effect_key" in source
    assert "ON intents(effect_key)" in source
    assert "WHERE kind = 'promotion.execution'" in source


def test_reader_requires_the_exact_index_sql_contract() -> None:
    source = _source(READER)
    assert '_PROMOTION_INDEX_NAME = "idx_promotion_execution_effect_key"' in source
    assert "CREATE UNIQUE INDEX idx_promotion_execution_effect_key" in source
    assert "ON intents(effect_key) WHERE kind = 'promotion.execution'" in source
    verifier = _segment(READER, _function(READER, "_verify_index_shape"))
    assert "sqlite_master" in verifier
    assert "_normalized_sql(master[\"sql\"])" in verifier
    assert "PRAGMA index_list('intents')" in verifier
    assert 'int(index["unique"]) != 1' in verifier
    assert 'int(index["partial"]) != 1' in verifier
    assert 'str(index["origin"]) != "c"' in verifier
    assert "PRAGMA index_info" in verifier
    assert 'str(columns[0]["name"]) != "effect_key"' in verifier


def test_every_security_read_verifies_index_before_selecting_rows() -> None:
    reader = _function(READER, "read_promotion_execution_intents")
    segment = _segment(READER, reader)
    verify_position = segment.index("_verify_index_shape(connection)")
    query_position = segment.index("SELECT * FROM intents")
    assert verify_position < query_position


def test_index_verifier_is_read_only() -> None:
    verifier = _segment(READER, _function(READER, "_verify_index_shape")).upper()
    for forbidden in (
        "CREATE INDEX",
        "DROP INDEX",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
    ):
        assert forbidden not in verifier
