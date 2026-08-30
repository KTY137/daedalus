from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.twin import FOURFOLD_PLANES, compile_reference_project, verify_forest_projection
from daedalus.twin import projection_verifier

REVISION = "7" * 40
NOW = "2026-08-29T21:58:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def test_projection_verifier_reuses_canonical_fourfold_identity_contracts() -> None:
    """The verifier must not grow a second plane list or binding-key authority."""

    source = inspect.getsource(projection_verifier)
    tree = ast.parse(source)
    function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_binding_key" not in function_names
    assert "FOURFOLD_PLANES" in source
    assert "binding.semantic_key" in source

    duplicated_plane_tuple = tuple(FOURFOLD_PLANES)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple):
            continue
        values = tuple(
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
        assert values != duplicated_plane_tuple


def test_reference_projection_round_trip_remains_revision_bound_and_deterministic() -> None:
    first = compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-fourfold-gardener",
    )
    second = compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-fourfold-gardener",
    )

    assert first.snapshot.to_json() == second.snapshot.to_json()
    assert first.snapshot.digest == second.snapshot.digest
    assert tuple(first.snapshot.plane_map) == FOURFOLD_PLANES
    assert all(binding.semantic_key[-1] == REVISION for binding in first.snapshot.bindings)

    report = verify_forest_projection(first.forest, first.snapshot)
    assert report.valid
    assert report.snapshot_sha256 == first.snapshot.digest
    assert not report.findings
