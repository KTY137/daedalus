from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.gates import assemble_gate0_release_report

ROOT = Path(__file__).resolve().parents[2]
RELEASE_PATH = ROOT / "daedalus" / "gates" / "release.py"
VERIFIER_PATH = ROOT / "daedalus" / "gates" / "release_verifier.py"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(module: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _call_names(node: ast.AST) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        target = item.func
        if isinstance(target, ast.Name):
            result.append((target.id, item.lineno))
        elif isinstance(target, ast.Attribute):
            result.append((target.attr, item.lineno))
    return result


def test_public_release_path_has_no_raw_trust_or_manual_closure_parameter() -> None:
    parameters = inspect.signature(assemble_gate0_release_report).parameters
    assert "trust_bundle" in parameters
    assert "collector_keyring" in parameters
    assert "closed" not in parameters
    assert "security_boundary_claimed" not in parameters
    assert not any(name.startswith("trusted_") for name in parameters)


def test_authentication_precedes_mechanical_projection_and_report_construction() -> None:
    function = _function(_module(RELEASE_PATH), "assemble_gate0_release_report")
    calls = _call_names(function)
    authentication = [line for name, line in calls if name == "verify_evidence_trust_bundle"]
    mechanical = [line for name, line in calls if name == "strict_mechanical_blockers"]
    construction = [line for name, line in calls if name == "Gate0ReleaseReport"]
    assert len(authentication) == len(mechanical) == len(construction) == 1
    assert authentication[0] < mechanical[0] < construction[0]


def test_release_projection_contains_no_effectful_or_promotion_boundary() -> None:
    module = _module(RELEASE_PATH)
    verifier = _module(VERIFIER_PATH)
    forbidden_calls = {
        "Popen",
        "run",
        "system",
        "unlink",
        "promote_candidates",
        "merge_pull_request",
        "update_ref",
    }
    observed = {
        name
        for tree in (module, verifier)
        for name, _ in _call_names(tree)
    }
    assert forbidden_calls.isdisjoint(observed)


def test_closed_is_derived_only_from_the_complete_blocker_union() -> None:
    module = _module(RELEASE_PATH)
    report_class = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "Gate0ReleaseReport"
    )
    closed = next(
        node
        for node in report_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "closed"
    )
    returns = [node for node in ast.walk(closed) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    value = returns[0].value
    assert isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)
    assert isinstance(value.operand, ast.Attribute)
    assert value.operand.attr == "blockers"


def test_independent_verifier_reconstructs_then_rechecks_current_state() -> None:
    function = _function(
        _module(VERIFIER_PATH),
        "gate0_release_verification_blockers",
    )
    calls = _call_names(function)
    assembly_lines = [
        line for name, line in calls if name == "assemble_gate0_release_report"
    ]
    assert len(assembly_lines) == 2
    source = ast.unparse(function)
    assert "reconstructed.to_dict() != release.to_dict()" in source
    assert "blockers.update(current_projection.blockers)" in source
    assert "release.evidence_trust_bundle_sha256 != trust_bundle.digest" in source


def test_counter_review_does_not_claim_human_or_owner_authority() -> None:
    source = Path(__file__).read_text(encoding="utf-8").lower()
    assert "approved by owner" not in source
    assert "human review passed" not in source
    assert "gate 0 closed" not in source
