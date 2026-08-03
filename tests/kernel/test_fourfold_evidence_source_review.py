from __future__ import annotations

import ast
import inspect

import daedalus.kernel.fourfold_evidence as target


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(target))


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def test_module_has_no_approval_consumption_promotion_or_external_effect_authority() -> None:
    tree = _tree()
    forbidden_names = {
        "ApprovalLedger",
        "ConsumedOwnerApproval",
        "issue_owner_approval",
        "verify_owner_approval",
        "promote_candidates",
        "subprocess",
        "docker",
    }
    imported_or_called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            imported_or_called.add(node.id)
        elif isinstance(node, ast.Attribute):
            imported_or_called.add(node.attr)
        elif isinstance(node, ast.alias):
            imported_or_called.add(node.asname or node.name.rsplit(".", 1)[-1])

    assert forbidden_names.isdisjoint(imported_or_called)


def test_consumer_rebuilds_all_three_canonical_artifacts() -> None:
    source = inspect.getsource(target)

    assert "FourfoldSnapshot.from_dict(snapshot.to_dict())" in source
    assert "EvidencePacket.from_dict(packet.to_dict())" in source
    assert "NominationReceipt.from_dict(nomination.to_dict())" in source
    assert "rebuilt != snapshot" in source
    assert "rebuilt != packet" in source
    assert "rebuilt != nomination" in source


def test_gate_policy_has_no_partial_snapshot_bypass_switch() -> None:
    expectation = inspect.signature(target.FourfoldEvidenceExpectation)
    assembler = inspect.signature(target.assemble_fourfold_evidence_packet)
    verifier = inspect.getsource(target.verify_fourfold_evidence_packet)

    assert "require_complete" not in expectation.parameters
    assert "require_complete" not in assembler.parameters
    assert 'plane.status != "complete"' in verifier
    assert "if incomplete:" in verifier


def test_nomination_verifier_pins_candidate_evidence_and_policy() -> None:
    verifier = inspect.getsource(target.verify_fourfold_nomination_receipt)

    required_fragments = (
        "nomination.candidate_artifact_sha256",
        "expectation.candidate_artifact_sha256",
        "nomination.candidate_artifact_locator",
        "expectation.candidate_artifact_locator",
        "nomination.evidence_packet_sha256",
        "packet.digest",
        "nomination.policy_decision_sha256",
        "packet.policy_decision_sha256",
        "nomination.evidence_locator",
        "_snapshot_locator(snapshot)",
    )
    for fragment in required_fragments:
        assert fragment in verifier


def test_assembler_reverifies_before_returning_artifacts() -> None:
    packet_builder = _function("assemble_fourfold_evidence_packet")
    nomination_builder = _function("assemble_fourfold_nomination_receipt")

    packet_calls = {
        node.func.id
        for node in ast.walk(packet_builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    nomination_calls = {
        node.func.id
        for node in ast.walk(nomination_builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "verify_fourfold_evidence_packet" in packet_calls
    assert "verify_fourfold_evidence_packet" in nomination_calls
    assert "verify_fourfold_nomination_receipt" in nomination_calls
