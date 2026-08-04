from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "daedalus" / "kernel" / "promotion_effect_replay.py"


def test_projection_has_no_writer_or_effect_authority() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    forbidden_calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in {
            "grant",
            "begin",
            "finish",
            "begin_effect",
            "finish_effect",
            "_connect",
        }:
            forbidden_calls.append(function.attr)
    assert forbidden_calls == []
    assert "mode=ro" in text
    assert "PRAGMA query_only=ON" in text
    assert "INSERT " not in text
    assert "UPDATE " not in text
    assert "DELETE " not in text


def test_subject_binding_precedes_terminal_decode() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert text.index("start = _decode_start(row, capability)") < text.index(
        "_decode_terminal(row, start)"
    )
    assert "canonical_json(execution.to_dict())" in text
    assert '"lease_json": lease.to_json()' in text
    assert "len(rows) != 1" in text


def test_malformed_wire_is_checked_before_hydration() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "object_pairs_hook=pairs" in text
    assert "parse_constant=" in text
    assert "canonical_json(value) != raw" in text
    assert "unexpected field set" in text
    assert "canonical_sha(body) != declared" in text
