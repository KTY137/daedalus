from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "daedalus" / "gates" / "release.py"
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


def test_release_module_cannot_construct_gate_closure_or_owner_authority() -> None:
    for forbidden in (
        "build_gate0_report(",
        "closed=True",
        "security_boundary_claimed=True",
        "OwnerApproval(",
        "issue_owner_approval",
        "promote_candidates",
        "merge_pull_request",
        "update_pull_request",
    ):
        assert forbidden not in SOURCE
    assert "from .report import GateReport" in SOURCE
    assert "assert_strict_exact_head_with_bundle" in SOURCE
    assert "scan_event_store_writers" in SOURCE


def test_report_wire_boundary_is_exact_v2_noncoercing_and_digest_bound() -> None:
    assert '_REPORT_SCHEMA = "daedalus-gate-report/2"' in SOURCE
    for required in (
        '"event_store_writer_inventory_sha256"',
        '"event_store_writer_failures"',
    ):
        assert required in SOURCE
    validate = _text(_function("validate_strict_gate_report_payload"))
    for expression in (
        "set(payload) != _REPORT_FIELDS",
        "type(payload[\"gate\"]) is not int",
        "type(payload[field_name]) is not bool",
        "not isinstance(values, list)",
        "values != sorted(set(values))",
        "event_store_writer_inventory_sha256",
        "event_store_writer_failures",
        "dict(payload) != canonical",
        "gate report closed value is not derived",
        "gate report blockers are not derived",
        "gate report digest mismatch",
    ):
        assert expression in validate
    loader = _text(_function("load_strict_gate_report"))
    assert "object_pairs_hook=_reject_duplicate_keys" in loader


def test_release_assessment_authenticates_evidence_then_recomputes_live_inventory() -> None:
    verify = _text(_function("_assert_gate0_release"))
    strict_report = verify.index("strict_gate_report_sha256(report)")
    bindings = verify.index("mismatches = []")
    trust = verify.index("assert_strict_exact_head_with_bundle(")
    artifacts = verify.index("_required_release_artifacts(index)")
    writer = verify.index("_live_writer_inventory(")
    closed = verify.index("if not report.closed")
    owner = verify.index("if not report.owner_approval_enforced")
    assert strict_report < bindings < trust < artifacts < writer < closed < owner
    for expression in (
        "report_revision != current",
        "index.source_revision != current",
        "bundle.source_revision != current",
        "index.source_tree_revision != current_tree",
        "bundle.source_tree_revision != current_tree",
        "report_registry != index.registry_sha256",
        "bundle.registry_sha256 != index.registry_sha256",
        "report.event_store_writer_inventory_sha256 != live_writer_digest",
        "report.event_store_writer_failures != live_writer_failures",
        "live Event-Store writer blockers remain",
    ):
        assert expression in verify


def test_live_writer_inventory_is_revision_bound_and_fail_closed() -> None:
    inventory = _text(_function("_live_writer_inventory"))
    assert "scan_event_store_writers(" in inventory
    assert "source_revision=current_revision" in inventory
    assert "except WriterInventoryError as exc" in inventory
    assert "Gate0ReleaseBindingError" in inventory
    assert "inventory.blockers" in inventory


def test_receipt_is_constructed_only_after_complete_release_assessment() -> None:
    issue = _text(_function("issue_gate0_release_receipt"))
    assessment = issue.index(
        "report_sha256, report_artifact_sha256 = _assert_gate0_release("
    )
    placeholder = issue.index("placeholder = Gate0ReleaseReceipt(")
    signature = issue.index("signature_sha256=_signature(")
    assert assessment < placeholder < signature
    assert "release receipt predates authenticated trust bundle" in issue


def test_release_and_collector_keys_have_distinct_scoped_keyrings() -> None:
    issue = _text(_function("issue_gate0_release_receipt"))
    verify = _text(_function("verify_gate0_release_receipt"))
    assert "collector_keyring: Mapping[tuple[str, str], bytes | str]" in issue
    assert "verifier_secret: bytes | str" in issue
    assert "collector_keyring: Mapping[tuple[str, str], bytes | str]" in verify
    assert "verifier_keyring: Mapping[tuple[str, str], bytes | str]" in verify
    assert "(receipt.verifier_id, receipt.verifier_key_id)" in verify
    assert "verifier_keyring.get(receipt.verifier_key_id)" not in verify


def test_receipt_signature_precedes_live_reassessment_and_exact_binding_checks() -> None:
    verify = _text(_function("verify_gate0_release_receipt"))
    signature = verify.index("hmac.compare_digest")
    time_check = verify.index('instant = _as_utc(now, "now")')
    reassess = verify.index(
        "report_sha256, report_artifact_sha256 = _assert_gate0_release("
    )
    bindings = verify.index("expected = {")
    assert signature < time_check < reassess < bindings
    for expression in (
        '"verifier_id"',
        '"source_revision"',
        '"source_tree_revision"',
        '"gate_report_sha256"',
        '"gate_report_artifact_sha256"',
        '"evidence_index_sha256"',
        '"trust_bundle_sha256"',
        '"requirements_sha256"',
        "release receipt predates authenticated trust bundle",
    ):
        assert expression in verify


def test_release_receipt_provenance_is_exact_and_status_cannot_be_forged() -> None:
    receipt = _text(_class("Gate0ReleaseReceipt"))
    for expression in (
        'self.status != "passed"',
        "self.provenance.origin != _RELEASE_RECEIPT_ORIGIN",
        "self.provenance.source_revision != self.source_revision",
        "self.provenance.created_at != self.verified_at",
        "self.provenance.trace_id != self.receipt_id",
        "tuple(self.provenance.input_digests) != expected_inputs",
        'body["signature_sha256"] = "0" * 64',
    ):
        assert expression in receipt
    assert "issubset" not in receipt


def test_release_verifier_requires_report_and_effect_inventory_artifacts() -> None:
    assert "_REQUIRED_RELEASE_ARTIFACT_KINDS = frozenset(" in SOURCE
    assert '"gate-report", "effect-inventory"' in SOURCE
    required = _text(_function("_required_release_artifacts"))
    assert "required_artifact_kinds" in required
    assert 'by_kind["gate-report"]' in required
    assert 'by_kind["effect-inventory"]' in required


def test_untrusted_receipt_loader_rejects_recursive_duplicate_keys() -> None:
    loader = _text(_function("load_gate0_release_receipt"))
    assert "object_pairs_hook=_reject_duplicate_keys" in loader
    parser = _text(_function("parse_gate0_release_receipt"))
    assert "Gate-0 release receipt must be an object" in parser
    assert "provenance must be an object" in parser
