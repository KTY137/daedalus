from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "daedalus" / "gates" / "fault_matrix.py"
MANIFEST = ROOT / "configs" / "gates" / "g0-provider-target-receipt-retention-fault-matrix.json"


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in _tree().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _class(name: str) -> ast.ClassDef:
    matches = [
        node
        for node in _tree().body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _method(class_name: str, method_name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in _class(class_name).body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    ]
    assert len(matches) == 1
    return matches[0]


def test_contract_module_has_no_fault_execution_or_mutation_capability() -> None:
    tree = _tree()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert imports.isdisjoint(
        {
            "subprocess",
            "socket",
            "sqlite3",
            "shutil",
            "tempfile",
            "requests",
            "httpx",
            "urllib",
        }
    )
    forbidden_calls = {
        "open",
        "write_bytes",
        "write_text",
        "mkdir",
        "unlink",
        "replace",
        "rename",
        "connect",
        "run",
        "Popen",
        "begin_effect",
        "finish_effect",
        "retain",
        "promote_candidates",
    }
    calls = {
        qualified.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for qualified in [_name(node.func)]
        if qualified is not None
    }
    assert calls.isdisjoint(forbidden_calls)


def test_manifest_and_scenario_wire_claims_are_permanently_non_authorizing() -> None:
    scenario = ast.unparse(_method("FaultScenarioSpec", "to_dict"))
    manifest = ast.unparse(_method("FaultMatrixManifest", "to_dict"))
    receipt = ast.unparse(_method("FaultScenarioReceipt", "to_dict"))

    for claim in (
        "automatic_reexecution_allowed",
        "primary_checkout_mutation_allowed",
        "llm_evidence_allowed",
    ):
        assert f"'{claim}': False" in scenario
    for claim in (
        "inventory_complete_claimed",
        "faults_executed",
        "gate_transition_authorized",
        "closed",
    ):
        assert f"'{claim}': False" in manifest
    for claim in (
        "automatic_reexecution_performed",
        "llm_evidence_used",
        "gate_transition_authorized",
        "closed",
    ):
        assert f"'{claim}': False" in receipt


def test_verifier_requires_exact_revision_inventory_and_receipt_types() -> None:
    source = ast.unparse(_function("verify_fault_matrix_run"))

    assert "type(manifest) is not FaultMatrixManifest" in source
    assert "type(receipts) is not tuple" in source
    assert "type(item) is not FaultScenarioReceipt" in source
    assert "manifest.source_revision != source_revision" in source
    assert "duplicate scenario receipts" in source
    assert "missing = tuple(sorted(expected_ids - observed_ids))" in source
    assert "extra = tuple(sorted(observed_ids - expected_ids))" in source
    assert "receipt.scenario_spec_sha256 == spec.digest" in source
    assert "receipt.source_revision == source_revision" in source
    assert "receipt.harness_revision == harness_revision" in source
    assert "receipt.observed_outcome == spec.expected_outcome" in source
    assert "expected_markers.issubset(observed_markers)" in source
    assert "forbidden_markers.isdisjoint(observed_markers)" in source
    assert "receipt.primary_checkout_before_sha256 == receipt.primary_checkout_after_sha256" in source
    assert "receipt.automatic_reexecution_performed is False" in source
    assert "receipt.llm_evidence_used is False" in source


def test_only_exact_passing_bound_verification_can_project_gate_evidence() -> None:
    source = ast.unparse(
        _method("FaultMatrixVerificationReceipt", "to_fault_matrix_evidence")
    )

    assert "self.status != 'passed'" in source
    assert "manifest.matrix_id != self.matrix_id" in source
    assert "manifest.digest != self.manifest_sha256" in source
    assert "manifest.source_revision != self.source_revision" in source
    assert "status='passed'" in source
    assert "failure_count=0" in source
    assert "item.scenario_id for item in manifest.scenarios" in source


def test_pinned_retention_matrix_is_exact_non_trusting_and_no_auto_reexecution() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]

    assert payload["gate"] == 0
    assert len(payload["source_revision"]) == 40
    assert payload["scenario_count"] == len(scenarios) == 12
    assert [item["scenario_id"] for item in scenarios] == sorted(
        item["scenario_id"] for item in scenarios
    )
    assert len({item["injection_point"] for item in scenarios}) == 12
    assert all(item["automatic_reexecution_allowed"] is False for item in scenarios)
    assert all(item["primary_checkout_mutation_allowed"] is False for item in scenarios)
    assert all(item["llm_evidence_allowed"] is False for item in scenarios)
    assert "trusted" not in json.dumps(payload).lower()
    assert {
        "retention_before_effect_start_kill",
        "retention_after_effect_start_before_intent_kill",
        "retention_after_intent_before_cas_kill",
        "retention_cas_atomic_replace_kill",
        "retention_after_cas_before_event_kill",
        "retention_event_commit_kill",
        "retention_after_event_before_effect_terminal_kill",
        "retention_after_effect_terminal_before_return_kill",
        "retention_stale_revision_before_effect_start",
        "retention_primary_checkout_mutation_attempt",
        "retention_started_replay_no_auto_reexecute",
        "retention_terminal_replay_idempotent",
    } == {item["scenario_id"] for item in scenarios}


def test_verification_receipt_never_authorizes_gate_or_closure() -> None:
    source = ast.unparse(_method("FaultMatrixVerificationReceipt", "to_dict"))
    assert "'gate_transition_authorized': False" in source
    assert "'closed': False" in source
    assert "'inventory_complete': not (self.missing_scenario_ids or self.extra_scenario_ids)" in source
    assert "'primary_checkout_unchanged': self.status == 'passed'" in source
    assert "'automatic_reexecution_absent': self.status == 'passed'" in source
    assert "'llm_evidence_absent': self.status == 'passed'" in source
