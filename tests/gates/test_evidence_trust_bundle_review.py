# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "daedalus" / "gates" / "trust_bundle.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(SOURCE_PATH))


def _function(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _class(name: str) -> ast.ClassDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def _text(node: ast.AST) -> str:
    return ast.get_source_segment(SOURCE, node) or ""


def test_bundle_is_an_authentication_envelope_not_a_second_gate_authority() -> None:
    module = SOURCE
    assert "from .evidence import GateEvidenceIndex" in module
    assert "from .evidence_verifier import (" in module
    assert "assert_strict_exact_head" in module
    for forbidden in (
        "build_gate0_report(",
        "security_boundary_claimed=True",
        "closed=True",
        "merge_pull_request",
        "promote_candidates",
        "OwnerApproval(",
    ):
        assert forbidden not in module


def test_signature_is_verified_before_bundle_bindings_or_trust_projection() -> None:
    verify = _text(_function("verify_evidence_trust_bundle"))
    signature = verify.index("hmac.compare_digest")
    time_check = verify.index('instant = _as_utc(now, "now")')
    binding = verify.index("comparisons = {")
    workflow = verify.index("expected_workflows = {")
    evidence_sets = verify.index("exact_sets = {")
    assert signature < time_check < binding < workflow < evidence_sets
    for expression in (
        "expected_workflow_paths.items()",
        "set(adopted_paths) != set(expected_workflows)",
        "anchor.repository_path != adopted_paths[workflow_id]",
        "repository path mismatch",
    ):
        assert expression in verify


def test_collector_key_lookup_is_scoped_by_collector_and_key_identity() -> None:
    verify = _text(_function("verify_evidence_trust_bundle"))
    assert "(bundle.collector_id, bundle.collector_key_id)" in verify
    assert "keyring.get(bundle.collector_key_id)" not in verify
    assert "Mapping[tuple[str, str], bytes | str]" in verify


def test_workflow_definition_uses_component_containment_and_exact_bytes() -> None:
    safe = _text(_function("_safe_workflow_path"))
    for expression in (
        "root = repo_root.resolve(strict=True)",
        "_repo_path(repository_path",
        "PurePosixPath(normalized).parts",
        "candidate.is_symlink()",
        "candidate.resolve(strict=True)",
        "root not in resolved.parents",
        "resolved.is_file()",
    ):
        assert expression in safe
    digest = _text(_function("workflow_definition_sha256"))
    assert "hashlib.sha256(path.read_bytes()).hexdigest()" in digest


def test_issuer_binds_exact_index_evidence_and_no_ambient_trust_sets() -> None:
    issue = _text(_function("issue_evidence_trust_bundle"))
    for expression in (
        "set(workflow_paths) != set(workflow_map)",
        "index.digest",
        "evidence_requirements_sha256(index)",
        "item.digest for item in index.artifacts",
        "item.envelope_sha256 for item in index.runtimes",
        "item.matrix_sha256 for item in index.fault_matrices",
        "item.digest for item in index.reviews",
        "index.owner_decision.verifier_receipt_sha256",
        "collector_secret",
    ):
        assert expression in issue
    assert "os.environ" not in issue
    assert "requests." not in issue
    assert "github" not in issue.lower()


def test_bundle_provenance_is_exact_and_short_lived() -> None:
    value = _text(_class("EvidenceTrustBundle"))
    for expression in (
        "expires - issued > _MAX_BUNDLE_TTL",
        "self.provenance.origin != _TRUST_BUNDLE_ORIGIN",
        "self.provenance.source_revision != self.source_revision",
        "self.provenance.created_at != self.issued_at",
        "self.provenance.trace_id != self.bundle_id",
        "tuple(self.provenance.input_digests) != expected_inputs",
    ):
        assert expression in value
    assert "issubset" not in value


def test_issuance_and_verification_share_exact_evidence_time_bounds() -> None:
    bounds = _text(_function("_evidence_time_bounds"))
    for expression in (
        "index.generated_at",
        "item.completed_at",
        "item.built_at",
        "item.observed_at",
        "item.executed_at",
        "item.reviewed_at",
        "index.owner_decision.verified_at",
        "index.expires_at",
        "item.expires_at",
        "return max(retained_times), min(expiries)",
    ):
        assert expression in bounds
    issue = _text(_function("issue_evidence_trust_bundle"))
    verify = _text(_function("verify_evidence_trust_bundle"))
    for text in (issue, verify):
        assert "_evidence_time_bounds(index)" in text
        assert "trust bundle issuance predates retained evidence" in text
        assert "trust bundle outlives retained evidence" in text


def test_strict_wrapper_derives_every_trust_set_from_authenticated_bundle() -> None:
    wrapper = _text(_function("assert_strict_exact_head_with_bundle"))
    assert wrapper.index("verify_evidence_trust_bundle(") < wrapper.index(
        "assert_strict_exact_head("
    )
    for expression in (
        "trusted_requirements_sha256s=(bundle.requirements_sha256,)",
        "trusted_iron_plan_sha256s=(bundle.iron_plan_sha256,)",
        "trusted_registry_sha256s=(bundle.registry_sha256,)",
        "item.workflow_evidence_sha256",
        "bundle.artifact_evidence_sha256s",
        "bundle.runtime_envelope_sha256s",
        "bundle.fault_matrix_sha256s",
        "bundle.review_evidence_sha256s",
        "bundle.owner_verifier_sha256s",
    ):
        assert expression in wrapper


def test_untrusted_wire_boundary_rejects_duplicates_and_string_arrays() -> None:
    parser = _text(_function("parse_evidence_trust_bundle"))
    for expression in (
        "workflow_anchors must be an array",
        "must be an object",
        "artifact_evidence_sha256s",
        "runtime_envelope_sha256s",
        "fault_matrix_sha256s",
        "review_evidence_sha256s",
        "owner_verifier_sha256s",
    ):
        assert expression in parser
    loader = _text(_function("load_evidence_trust_bundle"))
    assert "object_pairs_hook=_reject_duplicate_keys" in loader
