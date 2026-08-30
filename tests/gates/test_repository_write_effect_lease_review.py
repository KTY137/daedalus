# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus/gates/repository_write_effect_lease.py"
SOURCE = TARGET.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    rows = [
        node
        for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _class(name: str) -> ast.ClassDef:
    rows = [
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _method(class_name: str, method_name: str) -> ast.FunctionDef:
    rows = [
        node
        for node in _class(class_name).body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    ]
    assert len(rows) == 1
    return rows[0]


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def test_module_imports_no_writer_process_network_or_promotion_authority() -> None:
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported.intersection(
        {"os", "shutil", "socket", "sqlite3", "subprocess", "tempfile"}
    )
    assert "gated_writes" not in SOURCE
    assert "promotion_execution" not in SOURCE


def test_public_verifier_has_no_callback_provider_or_writer_smuggling() -> None:
    function = _function("verify_repository_write_effect_leases")
    assert function.args.vararg is None
    assert function.args.kwarg is None
    names = [item.arg for item in function.args.args]
    names.extend(item.arg for item in function.args.kwonlyargs)
    assert names == [
        "classification",
        "blobs",
        "origin_attestation",
        "guard_manifest",
        "runtime_subjects",
        "runtime_trust_ledgers",
        "effect_subjects",
        "collector_keyring",
        "expected_collector_id",
        "guard_keyring",
        "expected_guard_authority_id",
        "current_revision",
        "now",
        "repository_root",
    ]
    assert not any(
        token in name
        for name in names
        for token in ("callback", "provider", "executor", "writer", "outcome")
    )


def test_predecessor_is_verified_before_any_effect_inspection() -> None:
    function = _function("verify_repository_write_effect_leases")
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    lines: dict[str, list[int]] = {}
    for call in calls:
        lines.setdefault(_call_name(call), []).append(call.lineno)
    assert len(lines["verify_repository_write_runtime_conformance"]) == 1
    assert len(lines["materialize_repository_write_evidence"]) == 1
    assert len(lines["_verify_predecessor_chain"]) == 1
    assert len(lines["_inspect_subject"]) == 1
    assert lines["verify_repository_write_runtime_conformance"][0] < lines[
        "materialize_repository_write_evidence"
    ][0]
    assert lines["materialize_repository_write_evidence"][0] < lines[
        "_verify_predecessor_chain"
    ][0]
    assert lines["_verify_predecessor_chain"][0] < lines["_inspect_subject"][0]


def test_only_read_only_effect_replay_projections_are_called() -> None:
    calls = {_call_name(node) for node in ast.walk(TREE) if isinstance(node, ast.Call)}
    assert "inspect_effect_execution" in calls
    assert "inspect_runtime_effect_execution" in calls
    assert not calls.intersection(
        {
            "grant",
            "begin",
            "begin_effect",
            "finish",
            "finish_effect",
            "revoke",
            "retry",
            "issue_effect_lease",
            "issue_runtime_bound_effect_lease",
            "promote_candidates",
            "Popen",
            "connect",
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
        }
    )


def test_missing_and_started_states_explicitly_forbid_automatic_reexecution() -> None:
    # Wire revision 2 added a third: the typed non-runtime replay the
    # classification row calls before it will admit a conformity binding.
    assert SOURCE.count("automatic re-execution is forbidden") == 3
    assert (
        "non-runtime replay is not terminal; automatic re-execution is forbidden"
        in SOURCE
    )
    assert "has no durable start; automatic re-execution is forbidden" in SOURCE
    assert "is not terminal; automatic re-execution is forbidden" in SOURCE


def test_exact_terminal_entrypoint_revision_and_subject_fences_remain() -> None:
    required = (
        "if set(subject_snapshot) != required_receipts:",
        "if subject.source_revision != revision:",
        "if subject.entrypoint_id != entrypoint_id:",
        "if terminal.receipt_sha256 != receipt_sha256:",
        "if replay.state.lower() != terminal_state:",
        "if terminal.execution_id != subject.execution.execution_id:",
        "if terminal.lease_sha256 != subject.lease.digest:",
    )
    for fence in required:
        assert fence in SOURCE


def test_runtime_bound_effect_is_joined_to_surface_runtime_conformance() -> None:
    assert (
        "subject.runtime_conformance_sha256\n"
        "                != runtime_record.conformance_receipt_sha256"
    ) in SOURCE
    assert "runtime-bound replay omitted authenticated runtime trust" in SOURCE
    # /2: a production surface is covered by a replayed runtime record OR
    # by a verified non-runtime excuse, and by exactly one of the two.
    assert (
        "if set(runtime_by_surface) | excused_surfaces != required_surfaces:"
        in SOURCE
    )
    assert "if declared_non_runtime != excused_surfaces:" in SOURCE
    assert "runtime_trust_record_sha256" in SOURCE


def test_report_cannot_claim_complete_semantic_evidence_or_gate_closure() -> None:
    payload = _method("RepositoryWriteEffectLeaseReport", "_payload")
    returns = [node for node in ast.walk(payload) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    value = returns[0].value
    assert isinstance(value, ast.Dict)
    constants = {
        key.value: item.value
        for key, item in zip(value.keys, value.values)
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and isinstance(item, ast.Constant)
    }
    assert constants["effect_lease_semantics_verified"] is True
    for field in (
        "guard_contract_semantics_verified",
        "primary_checkout_disjointness_verified",
        "retirement_semantics_verified",
        "semantic_receipts_verified",
        "evidence_authenticated",
        "gate_report_bound",
        "closed",
    ):
        assert constants[field] is False


def test_public_result_types_are_frozen_and_data_only() -> None:
    for name in (
        "EffectLeaseReplaySubject",
        "EffectLeaseReplayRecord",
        "RepositoryWriteEffectLeaseReport",
    ):
        node = _class(name)
        assert any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "dataclass"
            and any(
                keyword.arg == "frozen"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in decorator.keywords
            )
            for decorator in node.decorator_list
        )
        methods = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not methods.intersection(
            {"execute", "grant", "begin", "finish", "revoke", "promote", "retry"}
        )
