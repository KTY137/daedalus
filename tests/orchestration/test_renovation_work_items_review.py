from __future__ import annotations

import ast
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "daedalus"
    / "orchestration"
    / "work_items.py"
)


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def test_review_contract_layer_has_no_effect_or_promotion_dependencies() -> None:
    tree = _tree()
    forbidden_roots = {
        "subprocess",
        "socket",
        "tempfile",
        "shutil",
    }
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imported_roots.intersection(forbidden_roots)

    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "daedalus.kernel.effects",
        "daedalus.kernel.approvals",
        "OwnerApproval",
        "EffectLease",
        "promote_candidates",
        "os.system",
        "Popen",
    ):
        assert forbidden not in source


def test_review_plan_constructor_retains_cardinality_dependency_and_path_fences() -> None:
    source = ast.unparse(_function("__post_init__"))
    assert "len(items) != 2" in source
    assert "set(by_kind) != set(_WORK_KINDS)" in source
    assert "sync_item.depends_on != (rename_item.work_item_id,)" in source
    assert "rename_paths.intersection(sync_paths)" in source
    assert "covered_planes != set(FOURFOLD_PLANES)" in source


def test_review_consumer_rebuilds_inputs_and_refuses_incomplete_planes() -> None:
    source = ast.unparse(_function("verify_renovation_plan"))
    assert "RenovationPlan.from_dict(plan.to_dict())" in source
    assert "MissionContract.from_dict(mission.to_dict())" in source
    assert "FourfoldSnapshot.from_dict(base_snapshot.to_dict())" in source
    assert "plane.status != 'complete'" in source
    assert "mission.digest" in source
    assert "base_snapshot.digest" in source


def test_review_parser_requires_complete_canonical_wire_equality() -> None:
    source = ast.unparse(_function("parse_renovation_plan"))
    assert "dict(payload) != plan.to_dict()" in source
    assert "Renovation plan wire is not canonical" in source


def test_review_work_item_provenance_is_exact_not_subset_based() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "tuple(self.provenance.input_digests) != expected_inputs" in source
    assert source.count("must bind exactly") >= 2
