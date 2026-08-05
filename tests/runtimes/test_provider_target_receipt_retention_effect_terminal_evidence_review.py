from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence as module


def _source() -> str:
    return inspect.getsource(module)


def test_effect_terminal_evidence_module_has_no_effect_or_promotion_authority() -> None:
    source = _source()
    tree = ast.parse(source)
    forbidden_import_roots = {
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
    }
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported_roots & forbidden_import_roots

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {
        "grant",
        "begin",
        "begin_effect",
        "finish",
        "finish_effect",
        "retain",
        "record_intent",
        "put_bytes",
        "write_bytes",
        "write_text",
        "open",
        "connect",
        "run",
        "Popen",
        "merge_pull_request",
        "enable_auto_merge",
    }


def test_public_verifier_performs_two_replays_with_identity_fences() -> None:
    source = inspect.getsource(
        module.verify_provider_target_receipt_retention_effect_terminal_evidence
    )
    assert source.count("inspect_effect_execution(authorization, execution)") == 2
    assert source.count("_effect_store_identity(effect_store_path)") == 3
    assert source.index("store_before =") < source.index("first = inspect_effect_execution")
    assert source.index("store_mid =") > source.index("first = inspect_effect_execution")
    assert source.index("second = inspect_effect_execution") > source.index("store_mid =")
    assert source.index("store_after =") > source.index("second = inspect_effect_execution")
    assert "if first != second:" in source
    assert "terminal.output_digests != (" in source
    assert "completed_evidence.receipt_artifact_sha256" in source


def test_receipt_permanently_refuses_authority_escalation() -> None:
    source = inspect.getsource(
        module.ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt.to_dict
    )
    for claim in (
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "owner_approval_issued",
        "promotion_authorized",
        "gate_transition_authorized",
        "closed",
    ):
        assert claim in module._FALSE_CLAIMS
    assert "**{field: False for field in _FALSE_CLAIMS}" in source
