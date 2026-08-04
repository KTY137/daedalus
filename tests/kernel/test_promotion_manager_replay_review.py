from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOADER = ROOT / "daedalus" / "kairos" / "gated_writes.py"
REPLAY = ROOT / "daedalus" / "kairos" / "promotion_manager_replay.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _method(path: Path, class_name: str, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return child
    raise AssertionError(f"missing {class_name}.{name}")


def _segment(path: Path, node: ast.AST) -> str:
    value = ast.get_source_segment(_source(path), node)
    assert value is not None
    return value


def test_loader_installs_replay_validation_after_manager_audit() -> None:
    source = _source(LOADER)
    manager_call = "install_promotion_manager_boundary(globals())"
    replay_call = "install_promotion_manager_replay_boundary(globals())"
    assert manager_call in source
    assert replay_call in source
    assert source.index(manager_call) < source.index(replay_call)


def test_begin_refuses_to_trust_invalid_persisted_completion() -> None:
    begin = _segment(
        REPLAY,
        _method(REPLAY, "_ReplayAuditedExecutionLedger", "begin"),
    )
    assert "validate_persisted_manager_completion(completion)" in begin
    assert "except PromotionManagerReplayError" in begin
    assert "replace(result, execute=False, completion=None)" in begin


def test_completion_fixes_report_identity_before_canonical_terminal_write() -> None:
    complete = _segment(
        REPLAY,
        _method(REPLAY, "_ReplayAuditedExecutionLedger", "complete"),
    )
    for required in (
        'enriched["manager_audit"] = snapshot.to_dict()',
        'enriched["manager_audit_sha256"] = snapshot.digest',
        'enriched["integration_branch"] = assessed_branch',
        'enriched["integration_revision"] = assessed_revision',
        'enriched["fault"]',
    ):
        assert required in complete
    assessment = complete.index("manager_boundary._assess_completion(")
    branch_fix = complete.index('enriched["integration_branch"]')
    delegate = complete.rindex("self._delegate.complete(")
    assert assessment < branch_fix < delegate


def test_replay_parser_is_exact_and_semantic_not_digest_only() -> None:
    source = _source(REPLAY)
    for required in (
        "set(result) != keys",
        "manager audit digest mismatch",
        "success branch differs from allocation",
        "success branch was not retained",
        "refusal lacks branch deletion proof",
        "fault identity differs from allocation",
        "branchless fault lacks deletion proof",
    ):
        assert required in source
    validator = _segment(
        REPLAY,
        _function(REPLAY, "validate_persisted_manager_completion"),
    )
    assert "canonical_sha(audit)" in validator
    assert "report_branch != receipt.integration_branch" in validator
    assert "report_revision != receipt.integration_revision" in validator


def test_unknown_fault_revision_stays_pending() -> None:
    complete = _segment(
        REPLAY,
        _method(REPLAY, "_ReplayAuditedExecutionLedger", "complete"),
    )
    assert "except Exception as resolve_exc" in complete
    assert "PromotionManagerAuditPending" in complete
    assert "except BaseException" not in complete


def test_replay_layer_uses_original_canonical_ledger_constructor() -> None:
    installer = _segment(
        REPLAY,
        _function(REPLAY, "install_promotion_manager_replay_boundary"),
    )
    assert "state.ledger_constructor(*args, **kwargs)" in installer
    assert 'namespace["PromotionExecutionLedger"] = factory' in installer
    assert 'namespace["_MANAGER_AUDIT_V1_LEDGER_FACTORY"]' in installer


def test_replay_layer_adds_no_mutating_or_owner_authority() -> None:
    source = _source(REPLAY).lower()
    for forbidden in (
        "subprocess",
        "git worktree",
        "git merge",
        "path.write_text",
        "path.write_bytes",
        "issue_owner_approval",
        "merge_pull_request",
        "closed=true",
    ):
        assert forbidden not in source
