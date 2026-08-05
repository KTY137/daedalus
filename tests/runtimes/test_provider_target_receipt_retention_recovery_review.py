from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_target_receipt_retention_recovery as recovery


_FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "http",
    "os",
    "pathlib",
    "shutil",
    "socket",
    "sqlite3",
    "subprocess",
    "tempfile",
    "urllib",
}
_FORBIDDEN_CALL_NAMES = {
    "begin_effect",
    "finish_effect",
    "grant",
    "mark_completed",
    "mkdir",
    "open",
    "Popen",
    "put_bytes",
    "record_intent",
    "rename",
    "replace",
    "retain",
    "run",
    "system",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
}


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(recovery))


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def test_recovery_projection_has_no_effectful_import_or_call_surface() -> None:
    tree = _tree()
    imported_roots: set[str] = set()
    called: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                called.add(target.id)
            elif isinstance(target, ast.Attribute):
                called.add(target.attr)

    assert imported_roots.isdisjoint(_FORBIDDEN_IMPORT_ROOTS)
    assert called.isdisjoint(_FORBIDDEN_CALL_NAMES)


def test_public_projection_requires_exact_admission_and_revision_only() -> None:
    node = _function("decide_provider_target_receipt_retention_recovery")

    assert [argument.arg for argument in node.args.args] == ["admission"]
    assert [argument.arg for argument in node.args.kwonlyargs] == [
        "expected_source_revision"
    ]
    assert node.args.vararg is None
    assert node.args.kwarg is None

    exact_checks = [
        candidate
        for candidate in ast.walk(node)
        if isinstance(candidate, ast.Compare)
        and isinstance(candidate.left, ast.Call)
        and isinstance(candidate.left.func, ast.Name)
        and candidate.left.func.id == "type"
        and len(candidate.left.args) == 1
        and isinstance(candidate.left.args[0], ast.Name)
        and candidate.left.args[0].id == "admission"
        and len(candidate.ops) == 1
        and isinstance(candidate.ops[0], ast.IsNot)
    ]
    assert len(exact_checks) == 1


def test_projection_reconstructs_and_double_fences_admission_identity() -> None:
    source = inspect.getsource(
        recovery.decide_provider_target_receipt_retention_recovery
    )

    first_restore = source.index(
        "ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(snapshot)"
    )
    decision = source.index("ProviderTargetReceiptRetentionRecoveryDecision(")
    second_restore = source.index(
        "ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(\n"
        "            final_snapshot"
    )
    final_digest = source.index("admission.digest != admission_digest")

    assert first_restore < decision < second_restore < final_digest
    assert "final_snapshot != snapshot" in source
    assert "final_restored != restored" in source
    assert "admission.source_revision != revision" in source
    assert "admission.execution_state != state" in source


def test_state_mapping_is_closed_and_never_requests_automatic_reexecution() -> None:
    assert recovery._STATE_DECISIONS == {
        "not_started": "request_fresh_start_authorization",
        "started": "manual_reconciliation_required",
        "COMPLETED": "verify_completed_retention_evidence",
        "FAILED": "terminal_failure_refusal",
        "CANCELLED": "terminal_cancellation_refusal",
    }
    source = inspect.getsource(
        recovery.ProviderTargetReceiptRetentionRecoveryDecision.to_dict
    )
    for claim in (
        '"persisted_state_reverified": False',
        '"automatic_reexecution_allowed": False',
        '"effect_start_authorized": False',
        '"retention_write_authorized": False',
        '"effect_terminalization_authorized": False',
        '"canonical_entrypoint_registered": False',
        '"gate_transition_authorized": False',
        '"closed": False',
    ):
        assert claim in source


def test_decision_container_cannot_smuggle_callback_or_mutable_authority() -> None:
    annotations = recovery.ProviderTargetReceiptRetentionRecoveryDecision.__annotations__

    assert tuple(annotations) == (
        "source_revision",
        "admission_sha256",
        "execution_state",
        "decision",
        "start_receipt_sha256",
        "terminal_receipt_sha256",
    )
    assert "Callable" not in inspect.getsource(recovery)
    assert "authorization" not in annotations
    assert "ledger" not in annotations
    assert "callback" not in annotations
