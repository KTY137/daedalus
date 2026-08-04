from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus" / "kairos" / "promotion_manager_boundary.py"


def test_branch_resolution_does_not_swallow_process_control_exceptions() -> None:
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TARGET))
    resolver = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_branch"
    )
    segment = ast.get_source_segment(source, resolver)
    assert segment is not None
    assert "except Exception" in segment
    assert "except BaseException" not in segment
