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


def _calls(function: ast.FunctionDef) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


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
    common = inspect.getsource(target._fourfold_evidence_binding_mismatches)

    assert "require_complete" not in expectation.parameters
    assert "require_complete" not in assembler.parameters
    assert 'plane.status != "complete"' in common
    assert "if incomplete:" in common
    assert "_fourfold_evidence_binding_mismatches" in _calls(
        _function("verify_fourfold_evidence_packet")
    )


def test_candidate_must_be_bound_by_snapshot_compiler_provenance() -> None:
    helper = inspect.getsource(target._require_snapshot_candidate_binding)
    assembler = inspect.getsource(target.assemble_fourfold_evidence_packet)
    common = inspect.getsource(target._fourfold_evidence_binding_mismatches)

    assert "candidate_sha not in snapshot.provenance.input_digests" in helper
    assert "_require_snapshot_candidate_binding(" in assembler
    assert "_require_snapshot_candidate_binding(" in common
    assert "_fourfold_evidence_binding_mismatches" in _calls(
        _function("verify_fourfold_evidence_packet")
    )
    assert "snapshot.provenance.input_digests" not in assembler.replace(
        "_require_snapshot_candidate_binding(", ""
    )


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


def test_negative_assembly_and_passed_verification_share_complete_binding_checks() -> None:
    helper_name = "_fourfold_evidence_binding_mismatches"
    assembler_calls = _calls(_function("assemble_fourfold_evidence_packet"))
    verifier_calls = _calls(_function("verify_fourfold_evidence_packet"))
    common_calls = _calls(_function(helper_name))
    assert helper_name in assembler_calls
    assert helper_name in verifier_calls
    assert "verify_fourfold_evidence_packet" in assembler_calls
    assert {"_canonical_packet", "_canonical_snapshot", "_require_snapshot_candidate_binding"} <= common_calls
    common = inspect.getsource(target._fourfold_evidence_binding_mismatches)
    required_bindings = (
        "expected_source_revision", "expected_snapshot", "incomplete_planes:",
        "subject", "candidate_digest", "candidate_locator", "fourfold_evidence_count",
        "fourfold_verdict", "snapshot_digest", "snapshot_locator", "snapshot_locator_unresolvable",
        "snapshot_locator_bytes", "fourfold_details", "fourfold_item_revision",
        "fourfold_item_candidate_provenance", "fourfold_item_forest_provenance",
        "fourfold_item_snapshot_provenance", "packet_revision", "packet_candidate_provenance",
        "packet_snapshot_provenance", "packet_attempt_provenance", "packet_policy_provenance",
    )
    for binding in required_bindings:
        assert binding in common
    for nomination_name in ("assemble_fourfold_nomination_receipt", "verify_fourfold_nomination_receipt"):
        nomination_calls = _calls(_function(nomination_name))
        assert "verify_fourfold_evidence_packet" in nomination_calls
        assert helper_name not in nomination_calls


def test_public_passed_verifier_has_no_negative_mode_or_conditional_status_bypass() -> None:
    assembler = inspect.signature(target.assemble_fourfold_evidence_packet)
    verifier = inspect.signature(target.verify_fourfold_evidence_packet)
    mode = assembler.parameters["status_mode"]
    assert mode.kind is inspect.Parameter.KEYWORD_ONLY
    assert mode.default == "passed_only"
    assert "status_mode" not in verifier.parameters
    for function in (
        target.FourfoldEvidenceExpectation,
        target.verify_fourfold_evidence_packet,
        target.assemble_fourfold_nomination_receipt,
        target.verify_fourfold_nomination_receipt,
    ):
        assert not {"require_complete", "require_passed", "allow_partial", "status_mode"} & set(
            inspect.signature(function).parameters
        )
    body = _function("verify_fourfold_evidence_packet").body
    status_guards = [
        statement for statement in body
        if isinstance(statement, ast.If)
        and isinstance(statement.test, ast.Compare)
        and isinstance(statement.test.left, ast.Attribute)
        and isinstance(statement.test.left.value, ast.Name)
        and statement.test.left.value.id == "packet"
        and statement.test.left.attr == "evaluation_status"
        and len(statement.test.ops) == 1
        and isinstance(statement.test.ops[0], ast.NotEq)
        and len(statement.test.comparators) == 1
        and isinstance(statement.test.comparators[0], ast.Constant)
        and statement.test.comparators[0].value == "passed"
    ]
    assert len(status_guards) == 1
    assert any(
        isinstance(node, ast.Constant) and node.value == "evaluation_status"
        for node in ast.walk(status_guards[0])
    )
