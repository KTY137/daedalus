from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.gates import guard_behavior_attestation as subject


SOURCE = Path(subject.__file__).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_module_has_no_execution_or_effect_authority():
    forbidden_imports = {
        "asyncio",
        "importlib",
        "multiprocessing",
        "os",
        "pathlib",
        "shutil",
        "socket",
        "sqlite3",
        "subprocess",
    }
    imported = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden_imports)
    calls = {
        node.func.id
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint({"eval", "exec", "open", "compile", "__import__"})


def test_verifier_authenticates_before_subject_projection():
    function = _function("verify_guard_behavior_attestation")
    source = ast.get_source_segment(SOURCE, function)
    assert source is not None
    signature_position = source.index("hmac.compare_digest")
    binding_position = source.index("exact_bindings =")
    time_position = source.index('instant = _as_utc(now, "now")')
    coverage_position = source.index("required_contracts =")
    return_position = source.index("return GuardBehaviorAttestationReport(")
    assert signature_position < binding_position < time_position < coverage_position
    assert coverage_position < return_position


def test_contract_coverage_is_exact_and_non_vacuous():
    function = _function("verify_guard_behavior_attestation")
    source = ast.get_source_segment(SOURCE, function)
    assert source is not None
    assert "case_contracts != required_contracts" in source
    assert "expected_outcomes != _OUTCOMES" in source
    assert "case.observed_outcome != case.expected_outcome" in source
    assert "guard structure report has no contracts" in source


def test_report_permanently_refuses_semantic_and_gate_claims():
    function = next(
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef)
        and node.name == "GuardBehaviorAttestationReport"
    )
    source = ast.get_source_segment(SOURCE, function)
    assert source is not None
    for claim in (
        '"guard_execution_replayed": False',
        '"guard_contract_semantics_verified": False',
        '"runtime_conformance_verified": False',
        '"semantic_receipts_verified": False',
        '"evidence_authenticated": False',
        '"gate_report_bound": False',
        '"closed": False',
    ):
        assert claim in source
    assert '"guard_behavior_attestation_authenticated": True' in source
    assert '"positive_and_negative_vectors_complete": True' in source


def test_issue_and_verify_signatures_accept_no_callback_or_executor():
    for name in (
        "issue_guard_behavior_attestation",
        "verify_guard_behavior_attestation",
    ):
        signature = inspect.signature(getattr(subject, name))
        assert not any(
            parameter.kind
            in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }
            for parameter in signature.parameters.values()
        )
        assert not any(
            token in parameter.lower()
            for parameter in signature.parameters
            for token in ("callback", "executor", "runner", "provider")
        )


def test_parser_is_bounded_strict_and_canonical():
    function = _function("parse_guard_behavior_attestation")
    source = ast.get_source_segment(SOURCE, function)
    assert source is not None
    assert "_MAX_ATTESTATION_BYTES" in source
    assert "object_pairs_hook=_reject_duplicate_keys" in source
    assert "parse_constant=_reject_nonfinite" in source
    assert "raw != canonical" in source
    assert 'b"\\x00"' in source


def test_all_security_subjects_are_in_the_signed_payload():
    function = next(
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef)
        and node.name == "GuardBehaviorAttestation"
    )
    source = ast.get_source_segment(SOURCE, function)
    assert source is not None
    for field in (
        '"source_revision"',
        '"classification_digest"',
        '"guard_structure_report_digest"',
        '"guard_structure_record_set_sha256"',
        '"harness_id"',
        '"harness_sha256"',
        '"runtime_manifest_digest"',
        '"cases"',
        '"case_set_sha256"',
        '"issued_at"',
        '"expires_at"',
    ):
        assert field in source
    assert 'signature_sha256="0" * 64' in SOURCE
