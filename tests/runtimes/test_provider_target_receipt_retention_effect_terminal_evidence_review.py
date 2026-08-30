# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
    assert source.index("authority_before") < source.index("store_before")
    assert source.index("store_before =") < source.index("first = inspect_effect_execution")
    assert source.index("store_mid =") > source.index("first = inspect_effect_execution")
    assert source.index("second = inspect_effect_execution") > source.index("store_mid =")
    assert source.index("store_after =") > source.index("second = inspect_effect_execution")
    assert "if first != second:" in source
    assert "authority_after != authority_before" in source
    assert "terminal.output_digests != (" in source
    assert "completed_evidence.receipt_artifact_sha256" in source


def test_authority_projection_requires_exact_revision_entrypoint_and_scope() -> None:
    source = inspect.getsource(module._authority_snapshot)
    assert "type(value) is not expected" in source
    assert "request.entrypoint_id != RETENTION_ENTRYPOINT" in source
    assert "lease.entrypoint_id != RETENTION_ENTRYPOINT" in source
    assert "authority_revisions != {revision}" in source
    assert "execution.requested_effects != lease.requested_effects" in source
    assert "execution.writable_paths != lease.effect_scope.writable_paths" in source
    assert "execution.kill_switch_generation != lease.kill_switch_generation" in source


def test_snapshot_is_independently_rebound_and_rehashed() -> None:
    source = inspect.getsource(module._require_completed_snapshot)
    assert "type(snapshot) is not EffectExecutionReplaySnapshot" in source
    assert 'snapshot.state != "COMPLETED"' in source
    assert "start.lease_sha256 != authorization.lease.digest" in source
    assert "start.execution_request_sha256 != execution.digest" in source
    assert "expected_start_sha = canonical_sha" in source
    assert "start_receipt_sha != expected_start_sha" in source
    assert "terminal.lease_sha256 != authorization.lease.digest" in source
    assert "terminal_start_sha != start_receipt_sha" in source
    assert "expected_terminal_sha = canonical_sha" in source
    assert "terminal_receipt_sha != expected_terminal_sha" in source
    assert "terminal receipt precedes its start" in source


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
