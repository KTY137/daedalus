# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/repository_write_runtime_conformance.py"
)


def _tree() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def test_module_has_no_write_effect_or_callback_authority() -> None:
    tree = _tree()
    source = TARGET.read_text(encoding="utf-8")
    forbidden_imports = {
        "os",
        "sqlite3",
        "subprocess",
        "socket",
        "docker",
        "git",
        "shutil",
        "tempfile",
        "importlib",
        "runpy",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(forbidden_imports)
    assert "Callable" not in source
    assert "Protocol" not in source
    assert "**kwargs" not in source

    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for forbidden in (
        "open",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "replace",
        "rename",
        "subprocess.run",
        "subprocess.Popen",
        "RuntimeTrustLedger.admit",
        "RuntimeTrustLedger.quarantine",
        "RuntimeTrustLedger.require_active",
        "begin_effect",
        "grant",
        "promote",
    ):
        assert forbidden not in calls


def test_caller_mappings_are_snapshotted_before_dependent_replay() -> None:
    source = TARGET.read_text(encoding="utf-8")
    assert source.count("blob_snapshot = _snapshot_bytes(blobs)") == 1
    assert source.count("subject_snapshot = _snapshot_subjects(runtime_subjects)") == 1
    assert source.count("ledger_snapshot = _snapshot_ledgers(runtime_trust_ledgers)") == 1
    assert source.count("dict(blobs.items())") == 1
    assert source.count("dict(subjects.items())") == 1
    assert source.count("dict(ledgers.items())") == 1
    assert "classification,\n        blob_snapshot," in source
    assert "materialize_repository_write_evidence(\n        classification,\n        blob_snapshot," in source


def test_predecessor_chain_is_verified_before_runtime_payloads() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "verify_repository_write_runtime_conformance"
    )
    calls = [
        (_call_name(node), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    guard = [
        line
        for name, line in calls
        if name == "verify_repository_write_guard_structure"
    ]
    materialize = [
        line
        for name, line in calls
        if name == "materialize_repository_write_evidence"
    ]
    chain = [line for name, line in calls if name == "_verify_predecessor_chain"]
    payload = [line for name, line in calls if name == "_runtime_payload"]
    subject = [line for name, line in calls if name == "_verify_runtime_subject"]
    assert len(guard) == len(materialize) == len(chain) == 1
    assert len(payload) == len(subject) == 1
    assert guard[0] < materialize[0] < chain[0] < payload[0] < subject[0]


def test_runtime_coverage_is_exact_non_vacuous_and_central() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "if not production_rows:",
        "row.guard is not GuardDisposition.CENTRAL",
        "if noncentral:",
        "if len(runtime_bindings) != 1:",
        "elif runtime_bindings:",
        "if set(subject_snapshot) != required_receipts:",
        "if set(ledger_snapshot) != required_runtime_ids:",
        "if len(payload_runtime_ids) != 1:",
    }
    for fragment in required:
        assert fragment in source


def test_runtime_subject_replays_persisted_and_typed_authority() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "ledger.records(subject.manifest.runtime_id)",
        "record.envelope_sha256 == subject.envelope.digest",
        '"state": (record.state, "ACTIVE")',
        '"probe_identity_sha256"',
        '"conformance_receipt_sha256"',
        '"runtime_manifest_sha256"',
        '"source_revision"',
        "now >= _parse_utc(record.expires_at",
        "subject.receipt.finished_at",
        "verify_production_runtime_envelope(",
        "trusted_envelope_sha256s=(record.envelope_sha256,)",
    }
    for fragment in required:
        assert fragment in source


def test_runtime_evidence_payload_is_exact_and_canonical() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "object_pairs_hook=_reject_duplicate_keys",
        "parse_constant=_reject_nonfinite",
        "if raw != canonical",
        '"receipt_schema"',
        '"receipt_sha256"',
        '"runtime_id"',
        '"conformant"',
        "RuntimeConformanceReceipt.CONTRACT_TYPE",
        "record.payload_sha256 != payload_sha256",
        'payload["conformant"] is not True',
    }
    for fragment in required:
        assert fragment in source


def test_report_cannot_launder_runtime_replay_into_complete_gate_evidence() -> None:
    source = TARGET.read_text(encoding="utf-8")
    true_claims = (
        '"origin_authenticated": True',
        '"source_anchor_semantics_verified": True',
        '"guard_contract_structure_verified": True',
        '"runtime_conformance_semantics_verified": True',
    )
    false_claims = (
        '"guard_contract_semantics_verified": False',
        '"effect_lease_semantics_verified": False',
        '"primary_checkout_disjointness_verified": False',
        '"retirement_semantics_verified": False',
        '"semantic_receipts_verified": False',
        '"evidence_authenticated": False',
        '"gate_report_bound": False',
        '"closed": False',
    )
    for claim in (*true_claims, *false_claims):
        assert source.count(claim) == 1
    for blocker in (
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-behavioral-verification-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
    ):
        assert source.count(blocker) == 1
    for forbidden in (
        "OwnerApproval",
        "PromotionReceipt",
        "issue_owner_approval",
        "apply_promotion",
    ):
        assert forbidden not in source


def test_replay_record_binds_surface_cas_trust_and_check_set() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for fragment in (
        '"surface_sha256": self.surface_sha256',
        '"locator": self.locator',
        '"runtime_id": self.runtime_id',
        '"envelope_sha256": self.envelope_sha256',
        '"trust_record_sha256": self.trust_record_sha256',
        '"probe_identity_sha256": self.probe_identity_sha256',
        '"conformance_receipt_sha256": self.conformance_receipt_sha256',
        '"runtime_manifest_sha256": self.runtime_manifest_sha256',
        '"observed_at": self.observed_at',
        '"expires_at": self.expires_at',
        '"check_set_sha256": self.check_set_sha256',
        "self.replay_sha256 != expected",
    ):
        assert fragment in source
